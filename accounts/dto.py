from core.utils import iso


def public_user(u):
    return {
        'id': u.id,
        'fullName': u.full_name,
        'email': u.email,
        'phone': u.phone,
        'emailVerified': u.email_verified,
        'isStaff': bool(u.is_staff and u.is_active),
        'createdAt': iso(u.created_at),
    }
