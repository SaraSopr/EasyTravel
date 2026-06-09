import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
# Enable debug logging for this module
logger.setLevel(logging.DEBUG)


async def send_otp_email(email: str, otp_code: str) -> bool:
    """
    Send OTP code to email using Resend API.
    
    Returns True if email was sent successfully, False otherwise.
    In dev mode (RESEND_API_KEY not configured), returns False immediately.
    In prod mode, sends email via Resend API and returns True if successful.
    """
    logger.debug(f"📧 send_otp_email called: email={email}, otp_code={otp_code}")
    
    # Dev mode: RESEND_API_KEY not configured
    if not settings.resend_api_key:
        logger.info("🔧 DEV MODE: OTP email skipped (RESEND_API_KEY not configured)")
        logger.debug(f"   → User email: {email}")
        logger.debug(f"   → OTP code would be: {otp_code}")
        return False
    
    logger.debug(f"🚀 PROD MODE: Sending OTP via Resend API to {email}")
    
    # Prod mode: Send email via Resend API
    try:
        async with httpx.AsyncClient() as client:
            html_content = f"""
            <h2>Verify your email</h2>
            <p>Your verification code is:</p>
            <h1 style="font-size: 32px; font-weight: bold; letter-spacing: 2px;">{otp_code}</h1>
            <p>This code will expire in 10 minutes.</p>
            <p>If you didn't request this code, please ignore this email.</p>
            """
            
            payload = {
                "from": settings.from_email,
                "to": email,
                "subject": "Verify your EasyTravel email",
                "html": html_content,
            }
            
            logger.debug(f"📤 Resend API request payload: from={settings.from_email}, to={email}, subject=Verify your EasyTravel email")
            logger.debug(f"   → API endpoint: https://api.resend.com/emails")
            logger.debug(f"   → Timeout: 10.0s")
            
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key[:10]}***",  # Hide full key in logs
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10.0,
            )
            
            logger.debug(f"📥 Resend API response: status_code={response.status_code}")
            
            if response.status_code == 200:
                logger.info(f"✅ OTP email sent successfully to {email}")
                logger.debug(f"   → Response body: {response.text[:100]}...")
                return True
            else:
                logger.error(
                    f"❌ Failed to send OTP email to {email}: HTTP {response.status_code}",
                )
                logger.debug(
                    f"   → Response body: {response.text}",
                )
                return False
    except httpx.TimeoutException as e:
        logger.error(f"⏱️  Timeout sending OTP to {email}: {str(e)}")
        return False
    except httpx.RequestError as e:
        logger.error(f"🔗 Network error sending OTP to {email}: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"💥 Unexpected error sending OTP to {email}: {type(e).__name__}: {str(e)}")
        logger.exception("Full traceback:")
        return False
