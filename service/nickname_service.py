from sqlalchemy import text

def validate_nicknames_batch(db, names: list[str]) -> tuple[list[str], list[str]]:
    """names를 한 번의 DB 쿼리로 검증. (verified, unverified) 반환"""
    if not names:
        return [], []
    rows = db.execute(text("""
        SELECT character_name
        FROM lostark.armory_profile_tb
        WHERE character_name = ANY(:names)
    """), {"names": names}).fetchall()
    found = {r[0] for r in rows}
    verified = [n for n in names if n in found]
    unverified = [n for n in names if n not in found]
    return verified, unverified
