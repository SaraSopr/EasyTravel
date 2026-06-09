export interface PasswordRequirements {
  minLength: boolean
  hasUppercase: boolean
  hasLowercase: boolean
  hasDigit: boolean
  hasSpecialChar: boolean
}

export const validatePassword = (password: string): PasswordRequirements => {
  return {
    minLength: password.length >= 8,
    hasUppercase: /[A-Z]/.test(password),
    hasLowercase: /[a-z]/.test(password),
    hasDigit: /\d/.test(password),
    hasSpecialChar: /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>?/]/.test(password),
  }
}

export const isPasswordValid = (password: string): boolean => {
  const req = validatePassword(password)
  return req.minLength && req.hasUppercase && req.hasLowercase && req.hasDigit && req.hasSpecialChar
}
