"""Beheertaken op de server.

    python -m eink_cloud.cli create-operator <gebruikersnaam> [--role admin|support]
"""

import argparse
import getpass
import os
import sys

from .db import make_sessionmaker
from .models import Operator
from .security import hash_password


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-operator", help="medewerker voor het managementsysteem aanmaken of wachtwoord resetten")
    c.add_argument("username")
    c.add_argument("--role", choices=("admin", "support"), default="support")
    args = p.parse_args()

    password = os.environ.get("EINK_OPERATOR_PASSWORD") or getpass.getpass("Wachtwoord: ")
    if len(password) < 10:
        sys.exit("wachtwoord moet minimaal 10 tekens zijn")
    sm = make_sessionmaker(os.environ.get("EINK_DATABASE_URL", "sqlite:///eink.db"))
    with sm() as session:
        op = session.get(Operator, args.username) or Operator(username=args.username)
        op.password_hash = hash_password(password)
        op.role = args.role
        session.add(op)
        session.commit()
    print(f"medewerker {args.username} ({args.role}) opgeslagen")


if __name__ == "__main__":
    main()
