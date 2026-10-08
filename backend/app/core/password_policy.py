"""Password rules (NIST SP 800-63B style): length over complexity, plus a block-list of passwords
that appear at the top of every breach corpus. Argon2id has no 72-byte limit, so long passphrases
are welcome."""

MIN_LENGTH = 8
MAX_LENGTH = 128

# Common passwords that would otherwise pass the "letter and number" rule (compared case-insensitively).
COMMON_PASSWORDS = frozenset(
    [
        "password1",
        "password12",
        "password123",
        "password1234",
        "passw0rd",
        "p@ssw0rd",
        "p@ssword1",
        "pa55word",
        "pa55w0rd",
        "qwerty123",
        "qwerty12",
        "qwerty1",
        "qwerty1234",
        "qwer1234",
        "asdf1234",
        "zxcv1234",
        "1q2w3e4r",
        "1q2w3e4r5t",
        "q1w2e3r4",
        "abc12345",
        "abcd1234",
        "abc123456",
        "a1b2c3d4",
        "1234abcd",
        "12345abc",
        "test1234",
        "test12345",
        "testing123",
        "temp1234",
        "letmein1",
        "letmein123",
        "welcome1",
        "welcome123",
        "welcome2024",
        "welcome2025",
        "welcome2026",
        "admin123",
        "admin1234",
        "administrator1",
        "root1234",
        "changeme1",
        "changeme123",
        "default1",
        "secret123",
        "secret1",
        "iloveyou1",
        "iloveyou2",
        "monkey123",
        "dragon123",
        "football1",
        "baseball1",
        "sunshine1",
        "princess1",
        "master123",
        "trustno1",
        "superman1",
        "batman123",
        "shadow123",
        "michael1",
        "jennifer1",
        "jordan23",
        "hunter123",
        "killer123",
        "starwars1",
        "summer2024",
        "summer2025",
        "winter2025",
        "spring2025",
        "autumn2025",
        "january2026",
        "october2026",
        "company123",
        "sales1234",
        "manager123",
        "user1234",
        "login123",
        "computer1",
        "internet1",
        "freedom1",
        "whatever1",
        "charlie1",
        "hello123",
        "hello1234",
        "goodluck1",
        "money123",
        "lovely123",
        "india123",
        "india@123",
        "bharat123",
        "mumbai123",
        "delhi1234",
        "bangalore1",
        "hyderabad1",
        "chennai123",
        "pune1234",
    ]
)


def password_problems(value: str) -> list[str]:
    problems = []
    if len(value) < MIN_LENGTH:
        problems.append(f"must be at least {MIN_LENGTH} characters")
    if len(value) > MAX_LENGTH:
        problems.append(f"must be at most {MAX_LENGTH} characters")
    if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
        problems.append("must contain at least one letter and one number")
    if value.lower() in COMMON_PASSWORDS:
        problems.append("is too common; choose something less predictable")
    return problems


def contextual_problems(value: str, email: str, name: str | None = None) -> list[str]:
    """Reject passwords built from the account's own email or name."""
    lowered = value.lower()
    local = email.split("@", 1)[0].lower()
    candidates = [local] + ([part.lower() for part in name.split()] if name else [])
    if any(len(c) >= 4 and c in lowered for c in candidates):
        return ["must not contain your name or email address"]
    return []
