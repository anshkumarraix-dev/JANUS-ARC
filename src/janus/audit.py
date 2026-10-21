"""Janus (ElderSync) — Tamper-Evident Audit Ledger CLI & Verifier.

Provides cryptographic verification of the SHA-256 hash chain in SQLite audit_log.
Formula:
    hash = sha256(prev_hash + canonical_json(row))
Genesis block uses 64 zero hex characters for prev_hash.

CLI Usage:
    python -m janus.audit verify [--db /path/to/janus.db]
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Tuple

from janus import storage


def verify_audit_chain(db_path: Optional[str] = None) -> Tuple[bool, Optional[int], str]:
    """Verify the cryptographic integrity of the audit_log hash chain.

    Recomputes the hash chain from row 1 to the end.
    Reports the first broken row upon failure.

    Returns:
        (is_valid, broken_row_id, message)
    """
    conn = storage.get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, ts, actor, role, tool, senior_id, transaction_id, outcome, prev_hash, hash
            FROM audit_log
            ORDER BY id ASC
            """
        )
        rows = cursor.fetchall()
        if not rows:
            return True, None, "Audit log is empty. Chain is intact."

        expected_prev_hash = "0" * 64

        for row in rows:
            row_id = row["id"]
            stored_prev_hash = row["prev_hash"]
            stored_hash = row["hash"]

            # 1. Verify prev_hash link
            if stored_prev_hash != expected_prev_hash:
                return (
                    False,
                    row_id,
                    f"Broken chain at row {row_id}: prev_hash mismatch. Expected '{expected_prev_hash}', got '{stored_prev_hash}'."
                )

            # 2. Recompute hash from canonical JSON
            row_data = {
                "actor": row["actor"],
                "id": row_id,
                "outcome": row["outcome"],
                "role": row["role"],
                "senior_id": row["senior_id"],
                "tool": row["tool"],
                "transaction_id": row["transaction_id"],
                "ts": row["ts"],
            }
            computed_hash = storage.compute_audit_hash(stored_prev_hash, row_data)

            # 3. Check hash match
            if stored_hash != computed_hash:
                return (
                    False,
                    row_id,
                    f"Broken chain at row {row_id}: hash mismatch. Expected '{computed_hash}', got '{stored_hash}'."
                )

            expected_prev_hash = stored_hash

        return True, None, f"Audit chain verified successfully ({len(rows)} records verified)."
    finally:
        conn.close()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Janus (ElderSync) Audit Chain Verifier")
    parser.add_argument("command", choices=["verify"], help="Audit command to execute")
    parser.add_argument("--db", default=None, help="Path to SQLite database file")

    args = parser.parse_args(argv)

    if args.command == "verify":
        is_valid, broken_id, message = verify_audit_chain(db_path=args.db)
        if is_valid:
            print(f"SUCCESS: {message}")
            return 0
        else:
            print(f"FAILURE: {message}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
