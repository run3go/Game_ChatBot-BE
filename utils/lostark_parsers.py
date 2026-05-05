import re
import json
import logging

logger = logging.getLogger(__name__)


def parse_tooltip_content(tooltip_str, target_title):
    try:
        if not tooltip_str:
            return ""
        data = json.loads(tooltip_str)
        for key in data:
            element = data[key]
            if element and element.get("type") == "ItemPartBox":
                val = element.get("value", {})
                if target_title in val.get("Element_000", ""):
                    raw_text = val.get("Element_001", "")
                    clean = re.sub(r"<br\s*/?>", "\n", raw_text, flags=re.IGNORECASE)
                    clean = re.sub(r"<[^>]+>", "", clean)
                    return clean.strip()
        return ""
    except Exception as e:
        logger.warning("툴팁 파싱 에러: %s", e)
        return ""


def split_core_options(core_opt_raw: str) -> dict:
    pattern = r'\[(\d+)P\]\s*(.*?)(?=\n\s*\[\d+P\]|$)'
    matches = re.findall(pattern, core_opt_raw, re.DOTALL)
    parsed = {f"p{i}": None for i in range(1, 7)}
    parsed.update({f"o{i}": None for i in range(1, 7)})
    for idx, (pts, desc) in enumerate(matches):
        if idx >= 6:
            break
        parsed[f"p{idx+1}"] = int(pts)
        parsed[f"o{idx+1}"] = desc.strip()
    return parsed


def split_gem_effect(gem_eff_raw: str) -> dict:
    parsed = {
        "req_will": None, "will_eff": None,
        "pt_type": None, "pt_val": None,
        "e1_name": None, "e1_lvl": None, "e1_val": None,
        "e2_name": None, "e2_lvl": None, "e2_val": None,
    }
    if not gem_eff_raw:
        return parsed

    req_match = re.search(r"필요 의지력\s*:\s*(\d+)", gem_eff_raw)
    if req_match:
        parsed["req_will"] = int(req_match.group(1))

    eff_match = re.search(r"의지력 효율\s*(\d+)", gem_eff_raw)
    if eff_match:
        parsed["will_eff"] = int(eff_match.group(1))

    pt_match = re.search(r"(질서|도약|혼돈|깨달음|진화)\s*포인트\s*:\s*(\d+)", gem_eff_raw)
    if pt_match:
        parsed["pt_type"] = pt_match.group(1)
        parsed["pt_val"] = int(pt_match.group(2))

    eff_matches = re.findall(r"\[(.*?)\]\s*Lv\.(\d+)\s*\n(.*?)(?=\n\[|$)", gem_eff_raw, re.DOTALL)
    num_pattern = r"[-+]?\s*(\d+\.?\d*)"

    if len(eff_matches) > 0:
        parsed["e1_name"] = eff_matches[0][0].strip()
        parsed["e1_lvl"] = int(eff_matches[0][1])
        val_match = re.search(num_pattern, eff_matches[0][2])
        parsed["e1_val"] = float(val_match.group(1)) if val_match else None

    if len(eff_matches) > 1:
        parsed["e2_name"] = eff_matches[1][0].strip()
        parsed["e2_lvl"] = int(eff_matches[1][1])
        val_match = re.search(num_pattern, eff_matches[1][2])
        parsed["e2_val"] = float(val_match.group(1)) if val_match else None

    return parsed


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-zA-Z_]+\s*", "", text)
    return text.strip()


def parse_ark_passive_description(desc_html):
    if not desc_html:
        return None, None, None
    clean_text = strip_html(desc_html)
    pattern = r"(\d+)티어\s+(.*?)\s+Lv\.(\d+)"
    match = re.search(pattern, clean_text)
    if match:
        return int(match.group(1)), match.group(2).strip(), int(match.group(3))
    return None, None, None


def parse_rank_level(description: str):
    if not description:
        return None, None
    match = re.search(r"(\d+)랭크\s*(\d+)레벨", description)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def parse_avatar_tooltip(tooltip_str):
    parsed = {
        "basic_stat": None, "basic_val": None,
        "intellect": 0, "courage": 0, "charm": 0, "kindness": 0,
        "source": None,
    }
    if not tooltip_str:
        return parsed
    try:
        tooltip = json.loads(tooltip_str)
        for key, item in tooltip.items():
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            item_value = item.get("value")
            if not item_value:
                continue
            if item_type == "ItemPartBox":
                el0 = item_value.get("Element_000", "")
                if "기본 효과" in el0:
                    basic_effect_str = strip_html(item_value.get("Element_001", ""))
                    match = re.search(r"([가-힣]+)\s*\+?(\d+\.?\d*)", basic_effect_str)
                    if match:
                        parsed["basic_stat"] = match.group(1)
                        parsed["basic_val"] = float(match.group(2))
            elif item_type == "SymbolString":
                title = item_value.get("titleStr", "")
                if "성향" in title:
                    tendency_str = strip_html(item_value.get("contentStr", ""))
                    for key_kor, field in [("지성", "intellect"), ("담력", "courage"), ("매력", "charm"), ("친절", "kindness")]:
                        m = re.search(rf"{key_kor}\s*:\s*(\d+)", tendency_str)
                        if m:
                            parsed[field] = int(m.group(1))
            elif item_type == "SingleTextBox":
                if "#5FD3F1" in str(item_value).upper():
                    parsed["source"] = strip_html(str(item_value))
        return parsed
    except Exception as e:
        logger.warning("아바타 툴팁 파싱 에러: %s", e)
        return parsed


def extract_card_description(tooltip_str):
    if not tooltip_str:
        return None
    try:
        tooltip = json.loads(tooltip_str)
        el_003 = tooltip.get("Element_003", {})
        if el_003.get("type") == "SingleTextBox":
            return strip_html(el_003.get("value", ""))
    except Exception:
        pass
    return None


def extract_basic_stats(effect_text):
    stats = {
        "무기 공격력": None, "물리 방어력": None, "마법 방어력": None,
        "힘": None, "민첩": None, "지능": None, "체력": None,
    }
    if not effect_text:
        return stats
    matches = re.findall(r"([가-힣\s]+)\s*\+([0-9,]+)", effect_text)
    for stat_name, stat_val in matches:
        clean_name = stat_name.strip()
        if clean_name in stats:
            stats[clean_name] = int(stat_val.replace(",", ""))
    return stats


def parse_additional_effect_to_json(item_type, text):
    if not text:
        return None
    result = {}
    clean_text = text.strip()

    if item_type == "어빌리티 스톤":
        matches = re.findall(r"\[(.*?)\]\s*Lv\.(\d+)", clean_text)
        result["engravings"] = {name: int(level) for name, level in matches}
    elif item_type in ["목걸이", "귀걸이", "반지", "무기", "투구", "상의", "하의", "장갑", "어깨"]:
        matches = re.findall(r"([가-힣\s]+)\s*\+([0-9.]+%?)", clean_text)
        for name, val in matches:
            suffix = "%" if val.endswith("%") else "+"
            result[f"{name.strip()} {suffix}"] = val
    elif item_type == "팔찌":
        stat_matches = re.findall(r"(특화|치명|신속|제압|인내|숙련|힘|민첩|지능|체력)\s*\+([0-9]+)", clean_text)
        if stat_matches:
            result["stats"] = {name: int(val) for name, val in stat_matches}
        special_text = re.sub(r"(특화|치명|신속|제압|인내|숙련|힘|민첩|지능|체력)\s*\+[0-9]+\s*", "", clean_text).strip()
        if special_text:
            effects = [e.strip() for e in special_text.split("LOSTARK_SPLIT_MARKER") if e.strip()]
            if effects:
                result["special_effects"] = effects
    elif item_type in ["보주", "부적", "나침반"]:
        result["description"] = clean_text

    return json.dumps(result, ensure_ascii=False)


def parse_basic_effect_to_json(text):
    if not text:
        return None
    stats = {}
    matches = re.findall(r"([가-힣\s]+)\s*\+([0-9,]+)", text)
    for stat_name, stat_val in matches:
        stats[stat_name.strip()] = int(stat_val.replace(",", ""))
    if not stats:
        return json.dumps({"description": text.strip()}, ensure_ascii=False)
    return json.dumps(stats, ensure_ascii=False)


def parse_equipment_tooltip(tooltip_str, item_name):
    quality, item_tier = 0, None
    basic_effect, additional_effect, ark_passive_effect = None, None, None
    enhancement_level, advanced_reinforcement = 0, 0

    match = re.search(r"\+(\d+)", item_name)
    if match:
        enhancement_level = int(match.group(1))

    if not tooltip_str:
        return (enhancement_level, quality, item_tier, basic_effect,
                additional_effect, ark_passive_effect, advanced_reinforcement)

    try:
        tooltip = json.loads(tooltip_str)
        for key, item in tooltip.items():
            if not isinstance(item, dict):
                continue
            i_type = item.get("type")
            i_val = item.get("value")

            if i_type == "SingleTextBox":
                clean_text = strip_html(str(i_val))
                if "[상급 재련]" in clean_text:
                    adv_match = re.search(r"(\d+)(?=단계)", clean_text)
                    if adv_match:
                        advanced_reinforcement = int(adv_match.group(1))
                    else:
                        nums = re.findall(r"\d+", clean_text)
                        if nums:
                            advanced_reinforcement = int(nums[0])

            elif i_type == "ItemTitle":
                quality = i_val.get("qualityValue", 0)
                t_match = re.search(r"티어\s*(\d+)", strip_html(i_val.get("leftStr2", "")))
                if t_match:
                    item_tier = int(t_match.group(1))

            elif i_type == "ItemPartBox":
                el0_raw = i_val.get("Element_000", "")
                el1_raw = i_val.get("Element_001", "")
                el0 = strip_html(el0_raw)
                el1 = strip_html(el1_raw)

                if "기본 효과" in el0:
                    basic_effect = el1
                elif "팔찌 효과" in el0:
                    text_with_sep = re.sub(r"<img[^>]*emoticon_tooltip_bracelet_[^>]*>", "LOSTARK_SPLIT_MARKER", str(el1_raw))
                    text_with_sep = re.sub(r"(?i)<br\s*/?>", " ", text_with_sep)
                    text_with_sep = re.sub(r"<[^>]+>", "", text_with_sep)
                    text_with_sep = re.sub(r"&[a-zA-Z_]+\s*", "", text_with_sep).strip()
                    additional_effect = text_with_sep if not additional_effect else f"{additional_effect} | {text_with_sep}"
                elif any(keyword in el0 for keyword in ["추가 효과", "연마 효과"]):
                    additional_effect = el1 if not additional_effect else f"{additional_effect} | {el1}"
                elif "아크 패시브" in el0:
                    ark_passive_effect = el1
                elif "특수 효과" in el0:
                    parts = [strip_html(p) for p in re.split(r'<BR>|<br>', str(el1_raw), flags=re.IGNORECASE)]
                    for part in parts:
                        if not part:
                            continue
                        if "최대 낙원력 :" in part:
                            additional_effect = part if not additional_effect else f"{additional_effect} | {part}"
                        elif "수치가 변동됩니다" in part:
                            continue
                        else:
                            basic_effect = part if not basic_effect else f"{basic_effect} | {part}"

            elif i_type == "IndentStringGroup":
                content_obj = i_val.get("Element_000", {}).get("contentStr", {})
                stone_effects = [strip_html(v.get("contentStr", "")) for k, v in content_obj.items() if strip_html(v.get("contentStr", ""))]
                if stone_effects:
                    stone_str = ", ".join(stone_effects)
                    additional_effect = stone_str if not additional_effect else f"{additional_effect} | {stone_str}"

    except Exception as e:
        logger.warning("장비 파싱 중 에러 (%s): %s", item_name, e)

    return (enhancement_level, quality, item_tier, basic_effect,
            additional_effect, ark_passive_effect, advanced_reinforcement)


def parse_gem_effects(eff_type_str, eff_opt_str):
    eff_name, eff_val, basic_atk_val = None, None, None

    if eff_type_str:
        match = re.search(r"(.+?)\s+([\d\.]+)\%\s+(.+)", eff_type_str)
        if match:
            eff_name = f"{match.group(1).strip()} {match.group(3).strip()}"
            eff_val = float(match.group(2))
        else:
            eff_name = eff_type_str

    if eff_opt_str:
        match = re.search(r"([\d\.]+)", eff_opt_str)
        if match:
            basic_atk_val = float(match.group(1))

    return eff_name, eff_val, basic_atk_val


def clean_number(val):
    if val is None or val == "":
        return 0.0
    try:
        return float(str(val).replace(",", ""))
    except ValueError:
        return 0.0


def parse_skill_tooltip(tooltip_str):
    res = {
        "cooldown": None, "mana_cost": 0, "weak_point": 0,
        "stagger": None, "attack_type": None, "is_counter": False,
        "skill_description": None, "rune_effect": None,
    }
    if not tooltip_str:
        return res
    try:
        tooltip = json.loads(tooltip_str)
    except Exception:
        return res

    for key, item in tooltip.items():
        if not isinstance(item, dict):
            continue
        i_type = item.get("type")
        i_val = item.get("value")

        if i_type == "CommonSkillTitle":
            cd_match = re.search(r"재사용 대기시간\s*([\d\.]+)초", strip_html(i_val.get("leftText", "")))
            if cd_match:
                res["cooldown"] = float(cd_match.group(1))

        elif i_type in ("MultiTextBox", "SingleTextBox"):
            mana_match = re.search(r"마나\s*(\d+)\s*소모", strip_html(str(i_val)))
            if mana_match:
                res["mana_cost"] = int(mana_match.group(1))

        if i_type == "SingleTextBox":
            val_text_raw = str(i_val)
            val_text_clean = strip_html(val_text_raw)

            wp_match = re.search(r"부위 파괴\s*:\s*레벨\s*(\d+)", val_text_clean)
            if wp_match:
                res["weak_point"] = int(wp_match.group(1))
            st_match = re.search(r"무력화\s*:\s*([가-힣]+)", val_text_clean)
            if st_match:
                res["stagger"] = st_match.group(1)
            at_match = re.search(r"공격 타입\s*:\s*([가-힣\s]+)", val_text_clean)
            if at_match:
                res["attack_type"] = at_match.group(1).strip()
            if "카운터 : 가능" in val_text_clean:
                res["is_counter"] = True

            if "<BR>" in val_text_raw.upper() and res["skill_description"] is None:
                if any(k in val_text_clean for k in ["부위 파괴", "무력화", "공격 타입"]):
                    parts = re.split(r"(?i)<br\s*/?>", val_text_raw)
                    if parts:
                        res["skill_description"] = strip_html(parts[0])

        if i_type == "ItemPartBox":
            el0 = i_val.get("Element_000", "")
            if "스킬 룬 효과" in el0:
                res["rune_effect"] = strip_html(i_val.get("Element_001", ""))

    return res


def to_jsonb(val):
    return json.dumps(val, ensure_ascii=False) if val else None
