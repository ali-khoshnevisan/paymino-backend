import re


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 8:
        problems.append('رمز عبور باید حداقل ۸ کاراکتر باشد.')
    if not re.search(r'[A-Za-z]', password) or not re.search(r'\d', password):
        problems.append('رمز عبور باید شامل حرف و عدد باشد.')
    if len(password) > 128:
        problems.append('رمز عبور بیش از حد طولانی است.')
    return problems
