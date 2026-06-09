import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models.otp import OtpVerification
from app.models.preference import UserPreference
from app.models.token_blacklist import TokenBlacklist
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    VerifyEmailRequest,
)
from app.schemas.user import UserOut
from app.utils.auth import create_access_token, generate_otp, hash_password, oauth2_scheme, verify_password
from app.utils.email import send_otp_email

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new user.
    
    - In dev mode (RESEND_API_KEY not set): returns AuthResponse with token immediately
    - In prod mode: returns MessageResponse with verification email sent message
    """
    # Normalize email
    email = payload.email.strip().lower()
    logger.info(f"📝 Register request: email={email}")
    logger.debug(f"   → from IP: {request.client.host if request.client else 'unknown'}")

    # Create user with is_verified=False initially
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        home_city=payload.home_city,
        age_range=payload.age_range,
        travel_with_children=payload.travel_with_children,
        is_verified=False,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        logger.warning(f"⚠️  Registration failed: email already registered ({email})")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    logger.debug(f"   → User created in DB (not yet committed): user_id={user.id}")

    preference = UserPreference(user_id=user.id)
    db.add(preference)
    await db.commit()
    await db.refresh(user)
    await db.refresh(preference)

    user.preferences = preference
    logger.debug(f"   → UserPreference created, user committed")

    logger.info(f"✅ New user registered: email={email}, user_id={user.id}")

    # Dev mode: RESEND_API_KEY not configured
    if not settings.resend_api_key:
        # Set user as verified immediately
        user.is_verified = True
        await db.commit()
        logger.info(f"🔧 DEV MODE: User auto-verified (is_verified=True)")
        logger.debug(f"   → Generating JWT token for {email}")
        
        # Return AuthResponse with token
        token = create_access_token({"sub": str(user.id)})
        logger.debug(f"   → Token generated successfully")
        return AuthResponse(
            access_token=token,
            user=UserOut.model_validate(user),
        )

    # Prod mode: Generate OTP and send email
    logger.info(f"🚀 PROD MODE: Generating OTP for {email}")
    otp_code = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    logger.debug(f"   → Expires at: {expires_at}")
    
    otp_record = OtpVerification(
        email=email,
        code=otp_code,
        expires_at=expires_at,
        used=False,
        attempts=0,
    )
    db.add(otp_record)
    await db.commit()
    logger.debug(f"   → OTP record saved to DB")
    
    # Send OTP email with actual code
    logger.info(f"📧 Sending OTP email to {email}")
    await send_otp_email(email, otp_code)
    
    logger.info(f"✉️  OTP email sent: email={email}")
    
    return MessageResponse(
        message="Verification code sent to your email. Please check your inbox."
    )


@router.post("/verify-email", response_model=AuthResponse)
@limiter.limit("5/minute")
async def verify_email(
    request: Request,
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify email with OTP code and get access token.
    """
    email = payload.email.strip().lower()
    code = payload.code.strip()
    logger.info(f"🔐 Verify email request: email={email}, code_length={len(code)}")
    logger.debug(f"   → from IP: {request.client.host if request.client else 'unknown'}")

    # Clean up expired and used OTPs
    logger.debug(f"🧹 Cleaning up expired/used OTPs...")
    deleted = await db.execute(
        delete(OtpVerification).where(
            (OtpVerification.expires_at < datetime.now(timezone.utc))
            | (OtpVerification.used == True)
        )
    )
    await db.flush()
    logger.debug(f"   → Deleted {deleted.rowcount} expired/used OTPs")

    # Find OTP record
    logger.debug(f"🔍 Searching for valid OTP record...")
    result = await db.execute(
        select(OtpVerification)
        .where(OtpVerification.email == email)
        .where(OtpVerification.used == False)
        .where(OtpVerification.expires_at >= datetime.now(timezone.utc))
        .order_by(OtpVerification.created_at.desc())
    )
    otp_record = result.scalar_one_or_none()

    if not otp_record:
        logger.warning(f"⚠️  OTP verification failed: no valid OTP found for {email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )
    
    logger.debug(f"   → Found OTP record (created at {otp_record.created_at}, expires at {otp_record.expires_at})")
    logger.debug(f"   → Current attempts: {otp_record.attempts}/5")

    # Check if too many failed attempts
    if otp_record.attempts >= 5:
        otp_record.used = True
        await db.commit()
        logger.error(f"❌ OTP verification blocked: too many attempts ({otp_record.attempts}) for {email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many invalid attempts. Please request a new code.",
        )

    # Verify code
    logger.debug(f"🔢 Comparing OTP codes...")
    if otp_record.code != code:
        otp_record.attempts += 1
        await db.commit()
        logger.warning(
            f"❌ Invalid OTP attempt for {email}: got '{code}', attempts now: {otp_record.attempts}/5"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    logger.debug(f"   → ✅ OTP code matches!")

    # Mark OTP as used
    otp_record.used = True
    await db.commit()
    logger.debug(f"   → OTP marked as used")

    # Find user and mark as verified
    logger.debug(f"🔎 Finding user record...")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        logger.error(f"💥 User not found during OTP verification: {email}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.debug(f"   → Found user: user_id={user.id}")
    
    user.is_verified = True
    await db.commit()
    logger.debug(f"   → User marked as verified (is_verified=True)")
    await db.refresh(user)

    # Load preferences
    result = await db.execute(
        select(User)
        .options(selectinload(User.preferences))
        .where(User.id == user.id)
    )
    user = result.scalar_one()
    logger.debug(f"   → User preferences loaded")

    logger.info(f"✅ Email verified successfully: {email}, user_id={user.id}")
    logger.debug(f"   → Generating JWT token...")

    token = create_access_token({"sub": str(user.id)})
    logger.debug(f"   → Token generated successfully")
    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Login with email and password.
    User must have verified their email first.
    """
    email = payload.email.strip().lower()
    logger.info(f"🔑 Login request: email={email}")
    logger.debug(f"   → from IP: {request.client.host if request.client else 'unknown'}")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        logger.warning(f"⚠️  Login failed: invalid credentials for {email}")
        logger.debug(f"   → User found: {user is not None}, Password valid: {user is not None and verify_password(payload.password, user.password_hash)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"   → Credentials valid")

    # Check if user has verified their email
    logger.debug(f"   → is_verified: {user.is_verified}")
    if not user.is_verified:
        logger.warning(f"❌ Login blocked: unverified email for {email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email first",
        )

    logger.debug(f"   → Email verified ✅")

    result = await db.execute(
        select(User)
        .options(selectinload(User.preferences))
        .where(User.id == user.id)
    )
    user = result.scalar_one()
    logger.debug(f"   → User preferences loaded")

    logger.info(f"✅ Login successful: email={email}, user_id={user.id}")
    logger.debug(f"   → Generating JWT token...")
    token = create_access_token({"sub": str(user.id)})
    logger.debug(f"   → Token generated successfully")
    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def logout(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timezone as tz

    from jose import JWTError, jwt as jose_jwt

    try:
        payload = jose_jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        jti: str | None = payload.get("jti")
        exp: int | None = payload.get("exp")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if jti and exp:
        expires_at = datetime.utcfromtimestamp(exp)  # naive UTC, matches TIMESTAMP WITHOUT TIME ZONE
        db.add(TokenBlacklist(jti=jti, expires_at=expires_at))
        await db.commit()

    logger.info("logout token_jti=%s", jti)
    return MessageResponse(message="Logged out successfully")
