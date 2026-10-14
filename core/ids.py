import uuid


def new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:16]}'


# Module-level callables so migrations can serialize them as field defaults.
def user_id():
    return new_id('usr')


def product_id():
    return new_id('p')


def variant_id():
    return new_id('v')


def order_id():
    return new_id('ord')


def order_item_id():
    return new_id('oi')


def invoice_id():
    return new_id('inv')


def ticket_id():
    return new_id('tkt')
