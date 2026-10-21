"""Short codes for people, shops and email addresses, for what these developer scripts print.

These scripts read the live database and print what they find. Printing real names and email
addresses puts customers' details into terminals, saved logs and screenshots, so the scripts print
a short code instead. The same person always gets the same code, so you can follow one person
through a report and from one script to another, but the code does not reveal the name.

To find out who a code belongs to, ask for the code of a name you are looking for:

    python ml/redact.py "Aoife Murphy"                the code for that name
    python ml/redact.py --email aoife@theshop.ie      the code for that address
    python ml/redact.py --shop "Main Street Deli"     the code for that shop

Codes are the same every time on one machine. Set ROSTER_REDACT_SALT to a word of your own to make
yours different from everybody else's.
"""
import hashlib
import os
import sys

_SALT = os.environ.get("ROSTER_REDACT_SALT", "roster-ml-output")


def _code(kind, value):
    text = str(value).strip().lower()
    return hashlib.sha256(f"{_SALT}|{kind}|{text}".encode("utf-8")).hexdigest()[:6]


def person(name):
    """A code for a person's name, such as staff-a3f9c1."""
    if not name or not str(name).strip():
        return "(no name)"
    return "staff-" + _code("person", name)


def place(name):
    """A code for a shop or business name, such as shop-7b21de."""
    if not name or not str(name).strip():
        return "(no name)"
    return "shop-" + _code("place", name)


def mailbox(address):
    """A code for an email address, such as mail-4c9e02."""
    if not address or not str(address).strip():
        return "(no email)"
    return "mail-" + _code("mailbox", address)


def scrub(text, names):
    """Free text with every one of these names replaced by its code, longest names first."""
    for name in sorted({str(n) for n in names if n and str(n).strip()}, key=len, reverse=True):
        text = text.replace(name, person(name))
    return text


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1 and not args[0].startswith("--"):
        print(person(args[0]))
    elif len(args) == 2 and args[0] == "--email":
        print(mailbox(args[1]))
    elif len(args) == 2 and args[0] == "--shop":
        print(place(args[1]))
    else:
        print(__doc__)
