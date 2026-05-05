import logging
from datetime import datetime, timezone
from sqlalchemy import text

from api.lostark_api import fetch_armory_data
from utils.lostark_parsers import (
    parse_tooltip_content,
    split_core_options,
    split_gem_effect,
    strip_html,
    parse_ark_passive_description,
    parse_rank_level,
    parse_avatar_tooltip,
    extract_card_description,
    parse_equipment_tooltip,
    parse_gem_effects,
    clean_number,
    parse_skill_tooltip,
    parse_basic_effect_to_json,
    parse_additional_effect_to_json,
)

logger = logging.getLogger(__name__)


def collect_character(character_name: str, db) -> bool:
    api_data = fetch_armory_data(character_name)
    if not api_data:
        return False

    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    try:
        _insert_profile(db, character_name, collected_at, api_data)
        _insert_equipment(db, character_name, collected_at, api_data)
        _insert_skills(db, character_name, collected_at, api_data)
        _insert_gems(db, character_name, collected_at, api_data)
        _insert_engravings(db, character_name, collected_at, api_data)
        _insert_cards(db, character_name, collected_at, api_data)
        _insert_card_effects(db, character_name, collected_at, api_data)
        _insert_avatars(db, character_name, collected_at, api_data)
        _insert_collectibles(db, character_name, collected_at, api_data)
        _insert_collectible_details(db, character_name, collected_at, api_data)
        _insert_ark_grid_cores(db, character_name, collected_at, api_data)
        _insert_ark_grid_gems(db, character_name, collected_at, api_data)
        _insert_ark_passive_points(db, character_name, collected_at, api_data)
        _insert_ark_passive_effects(db, character_name, collected_at, api_data)
        db.commit()
        logger.info("캐릭터 수집 완료: %s", character_name)
        return True
    except Exception:
        logger.exception("캐릭터 데이터 적재 실패: %s", character_name)
        db.rollback()
        return False


def _insert_profile(db, character_name, collected_at, api_data):
    p = api_data.get("ArmoryProfile")
    if not p:
        return

    s_dict = {s.get("Type"): clean_number(s.get("Value", 0)) for s in p.get("Stats", [])}
    t_dict = {t.get("Type"): int(t.get("Point", 0)) for t in p.get("Tendencies", [])}

    db.execute(text("""
        INSERT INTO lostark.armory_profile_tb (
            character_name, collected_at, server_name, character_class_name, character_level,
            item_avg_level, combat_power, character_image, expedition_level,
            town_level, town_name, title, guild_member_grade, guild_name,
            using_skill_point, total_skill_point, honor_point,
            stat_atk, stat_hp, stat_crit, stat_spec, stat_swift, stat_dom, stat_end, stat_exp,
            tend_intellect, tend_courage, tend_charm, tend_kindness
        ) VALUES (
            :character_name, :collected_at, :server_name, :character_class_name, :character_level,
            :item_avg_level, :combat_power, :character_image, :expedition_level,
            :town_level, :town_name, :title, :guild_member_grade, :guild_name,
            :using_skill_point, :total_skill_point, :honor_point,
            :stat_atk, :stat_hp, :stat_crit, :stat_spec, :stat_swift, :stat_dom, :stat_end, :stat_exp,
            :tend_intellect, :tend_courage, :tend_charm, :tend_kindness
        )
    """), {
        "character_name": character_name,
        "collected_at": collected_at,
        "server_name": p.get("ServerName"),
        "character_class_name": p.get("CharacterClassName"),
        "character_level": int(p.get("CharacterLevel", 0)),
        "item_avg_level": clean_number(p.get("ItemAvgLevel")),
        "combat_power": clean_number(p.get("CombatPower")),
        "character_image": p.get("CharacterImage"),
        "expedition_level": int(p.get("ExpeditionLevel", 0)),
        "town_level": p.get("TownLevel"),
        "town_name": p.get("TownName"),
        "title": p.get("Title"),
        "guild_member_grade": p.get("GuildMemberGrade"),
        "guild_name": p.get("GuildName"),
        "using_skill_point": p.get("UsingSkillPoint"),
        "total_skill_point": p.get("TotalSkillPoint"),
        "honor_point": p.get("HonorPoint"),
        "stat_atk": s_dict.get("공격력", 0),
        "stat_hp": s_dict.get("최대 생명력", 0),
        "stat_crit": s_dict.get("치명", 0),
        "stat_spec": s_dict.get("특화", 0),
        "stat_swift": s_dict.get("신속", 0),
        "stat_dom": s_dict.get("제압", 0),
        "stat_end": s_dict.get("인내", 0),
        "stat_exp": s_dict.get("숙련", 0),
        "tend_intellect": t_dict.get("지성", 0),
        "tend_courage": t_dict.get("담력", 0),
        "tend_charm": t_dict.get("매력", 0),
        "tend_kindness": t_dict.get("친절", 0),
    })


def _insert_equipment(db, character_name, collected_at, api_data):
    eq = api_data.get("ArmoryEquipment")
    if not eq:
        return

    rows = []
    for idx, i in enumerate(eq):
        item_name = i.get("Name", "")
        item_type = i.get("Type")
        enh_lvl, qual, tier, basic_eff_raw, add_eff_raw, ark_eff_raw, adv_reinf = parse_equipment_tooltip(i.get("Tooltip"), item_name)
        rows.append({
            "character_name": character_name,
            "slot_index": idx,
            "type": item_type,
            "name": item_name,
            "collected_at": collected_at,
            "icon": i.get("Icon"),
            "grade": i.get("Grade"),
            "honing_level": enh_lvl,
            "quality": qual,
            "item_tier": tier,
            "advanced_honing_level": adv_reinf,
            "basic_effect": parse_basic_effect_to_json(basic_eff_raw),
            "additional_effect": parse_additional_effect_to_json(item_type, add_eff_raw),
            "ark_passive_effect": ark_eff_raw,
        })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.armory_equipment_tb
            (character_name, slot_index, type, name, collected_at, icon, grade,
             honing_level, quality, item_tier, advanced_honing_level,
             basic_effect, additional_effect, ark_passive_effect)
            VALUES (:character_name, :slot_index, :type, :name, :collected_at, :icon, :grade,
                    :honing_level, :quality, :item_tier, :advanced_honing_level,
                    :basic_effect, :additional_effect, :ark_passive_effect)
        """), rows)


def _insert_skills(db, character_name, collected_at, api_data):
    skills = api_data.get("ArmorySkills", [])
    if not skills:
        return

    rows = []
    for skill in skills:
        s_lvl = skill.get("Level")
        pt = parse_skill_tooltip(skill.get("Tooltip"))
        rune = skill.get("Rune")
        rune_name = rune.get("Name") if rune else None
        rune_grade = rune.get("Grade") if rune else None

        t_info = {0: [None, None, None], 1: [None, None, None], 2: [None, None, None]}
        t1_name = None
        for t in skill.get("Tripods", []):
            if t.get("IsSelected"):
                tier = t.get("Tier")
                t_info[tier] = [t.get("Name"), t.get("Icon"), strip_html(t.get("Tooltip", ""))]
                if tier == 0:
                    t1_name = t.get("Name")

        if s_lvl == 1 and not rune_name and not t1_name:
            continue

        rows.append({
            "character_name": character_name,
            "skill_name": skill.get("Name"),
            "collected_at": collected_at,
            "skill_level": s_lvl,
            "type": skill.get("Type"),
            "cooldown": pt["cooldown"],
            "mana_cost": pt["mana_cost"],
            "weak_point": pt["weak_point"],
            "stagger": pt["stagger"],
            "attack_type": pt["attack_type"],
            "is_counter": pt["is_counter"],
            "tripod_1_name": t_info[0][0],
            "tripod_2_name": t_info[1][0],
            "tripod_3_name": t_info[2][0],
            "rune_name": rune_name,
            "rune_grade": rune_grade,
            "rune_effect": pt["rune_effect"],
        })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.armory_skills_tb
            (character_name, skill_name, collected_at, skill_level, type,
             cooldown, mana_cost, weak_point, stagger, attack_type, is_counter,
             tripod_1_name, tripod_2_name, tripod_3_name,
             rune_name, rune_grade, rune_effect)
            VALUES (:character_name, :skill_name, :collected_at, :skill_level, :type,
                    :cooldown, :mana_cost, :weak_point, :stagger, :attack_type, :is_counter,
                    :tripod_1_name, :tripod_2_name, :tripod_3_name,
                    :rune_name, :rune_grade, :rune_effect)
        """), rows)


def _insert_gems(db, character_name, collected_at, api_data):
    gem_data = api_data.get("ArmoryGem")
    if not gem_data:
        return

    gems = gem_data.get("Gems", [])
    if not gems:
        return

    effects = gem_data.get("Effects", {})
    skill_dict = {}
    for s in effects.get("Skills", []):
        slot = s.get("GemSlot")
        desc_list = s.get("Description", [])
        skill_dict[slot] = {
            "skill_name": s.get("Name"),
            "effect_option": s.get("Option"),
            "effect_type": desc_list[0] if desc_list else None,
        }

    rows = []
    for g in gems:
        slot = g.get("Slot")
        matched = skill_dict.get(slot, {})
        eff_name, eff_val, basic_atk_val = parse_gem_effects(matched.get("effect_type"), matched.get("effect_option"))
        rows.append({
            "character_name": character_name,
            "slot": slot,
            "collected_at": collected_at,
            "name": strip_html(g.get("Name")),
            "grade": g.get("Grade"),
            "level": g.get("Level"),
            "skill_name": matched.get("skill_name"),
            "effect_type_name": eff_name,
            "effect_type_value": eff_val,
            "basic_attack_boost_value": basic_atk_val,
            "icon": g.get("Icon"),
        })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.armory_gem_tb
            (character_name, slot, collected_at, name, grade, level, skill_name,
             effect_type_name, effect_type_value, basic_attack_boost_value, icon)
            VALUES (:character_name, :slot, :collected_at, :name, :grade, :level, :skill_name,
                    :effect_type_name, :effect_type_value, :basic_attack_boost_value, :icon)
        """), rows)


def _insert_engravings(db, character_name, collected_at, api_data):
    en = api_data.get("ArmoryEngraving")
    if not en:
        return

    effects = en.get("ArkPassiveEffects", [])
    if not effects:
        return

    rows = [{
        "character_name": character_name,
        "name": e.get("Name"),
        "collected_at": collected_at,
        "grade": e.get("Grade"),
        "level": e.get("Level"),
        "ability_stone_level": e.get("AbilityStoneLevel"),
        "description": strip_html(e.get("Description")),
    } for e in effects]

    if rows:
        db.execute(text("""
            INSERT INTO lostark.armory_engravings_tb
            (character_name, name, collected_at, grade, level, ability_stone_level, description)
            VALUES (:character_name, :name, :collected_at, :grade, :level, :ability_stone_level, :description)
        """), rows)


def _insert_cards(db, character_name, collected_at, api_data):
    card_data = api_data.get("ArmoryCard")
    if not card_data:
        return

    cards = card_data.get("Cards", [])
    if not cards:
        return

    rows = [{
        "character_name": character_name,
        "slot": c.get("Slot"),
        "collected_at": collected_at,
        "name": c.get("Name"),
        "icon": c.get("Icon"),
        "grade": c.get("Grade"),
        "awake_count": c.get("AwakeCount", 0),
        "awake_total": c.get("AwakeTotal", 0),
        "description": extract_card_description(c.get("Tooltip")),
    } for c in cards]

    if rows:
        db.execute(text("""
            INSERT INTO lostark.armory_card_tb
            (character_name, slot, collected_at, name, icon, grade, awake_count, awake_total, description)
            VALUES (:character_name, :slot, :collected_at, :name, :icon, :grade, :awake_count, :awake_total, :description)
        """), rows)


def _insert_card_effects(db, character_name, collected_at, api_data):
    card_data = api_data.get("ArmoryCard")
    if not card_data:
        return

    rows = []
    for effect_group in card_data.get("Effects", []):
        for item in effect_group.get("Items", []):
            rows.append({
                "character_name": character_name,
                "effect_name": item.get("Name"),
                "collected_at": collected_at,
                "description": item.get("Description"),
            })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.armory_card_effects_tb
            (character_name, effect_name, collected_at, description)
            VALUES (:character_name, :effect_name, :collected_at, :description)
        """), rows)


def _insert_avatars(db, character_name, collected_at, api_data):
    av = api_data.get("ArmoryAvatars")
    if not av:
        return

    rows = []
    for i in av:
        opts = parse_avatar_tooltip(i.get("Tooltip"))
        rows.append({
            "character_name": character_name,
            "name": i.get("Name"),
            "collected_at": collected_at,
            "type": i.get("Type"),
            "icon": i.get("Icon"),
            "grade": i.get("Grade"),
            "is_set": i.get("IsSet"),
            "is_inner": i.get("IsInner"),
            "basic_effect_stat": opts.get("basic_stat"),
            "basic_effect_value": opts.get("basic_val"),
            "tendency_intellect": opts.get("intellect"),
            "tendency_courage": opts.get("courage"),
            "tendency_charm": opts.get("charm"),
            "tendency_kindness": opts.get("kindness"),
            "source": opts.get("source"),
        })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.armory_avatars_tb
            (character_name, name, collected_at, type, icon, grade, is_set, is_inner,
             basic_effect_stat, basic_effect_value,
             tendency_intellect, tendency_courage, tendency_charm, tendency_kindness, source)
            VALUES (:character_name, :name, :collected_at, :type, :icon, :grade, :is_set, :is_inner,
                    :basic_effect_stat, :basic_effect_value,
                    :tendency_intellect, :tendency_courage, :tendency_charm, :tendency_kindness, :source)
        """), rows)


def _insert_collectibles(db, character_name, collected_at, api_data):
    co = api_data.get("Collectibles")
    if not co:
        return

    rows = [{
        "character_name": character_name,
        "type": i.get("Type"),
        "collected_at": collected_at,
        "icon": i.get("Icon"),
        "point": i.get("Point"),
        "max_point": i.get("MaxPoint"),
    } for i in co]

    if rows:
        db.execute(text("""
            INSERT INTO lostark.armory_collectibles_tb
            (character_name, type, collected_at, icon, point, max_point)
            VALUES (:character_name, :type, :collected_at, :icon, :point, :max_point)
        """), rows)


def _insert_collectible_details(db, character_name, collected_at, api_data):
    co = api_data.get("Collectibles")
    if not co:
        return

    rows = []
    for i in co:
        c_type = i.get("Type")
        for cp in i.get("CollectiblePoints") or []:
            rows.append({
                "character_name": character_name,
                "type": c_type,
                "point_name": cp.get("PointName"),
                "collected_at": collected_at,
                "point": cp.get("Point"),
                "max_point": cp.get("MaxPoint"),
            })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.armory_collectible_details_tb
            (character_name, type, point_name, collected_at, point, max_point)
            VALUES (:character_name, :type, :point_name, :collected_at, :point, :max_point)
        """), rows)


def _insert_ark_grid_cores(db, character_name, collected_at, api_data):
    ag = api_data.get("ArkGrid")
    if not ag:
        return

    rows = []
    for slot in ag.get("Slots") or []:
        core_opt_raw = parse_tooltip_content(slot.get("Tooltip"), "코어 옵션")
        opts = split_core_options(core_opt_raw)
        rows.append({
            "character_name": character_name,
            "slot_index": slot.get("Index"),
            "collected_at": collected_at,
            "name": slot.get("Name"),
            "grade": slot.get("Grade"),
            "point": slot.get("Point"),
            "icon": slot.get("Icon"),
            "level_1_point": opts["p1"], "level_1_option": opts["o1"],
            "level_2_point": opts["p2"], "level_2_option": opts["o2"],
            "level_3_point": opts["p3"], "level_3_option": opts["o3"],
            "level_4_point": opts["p4"], "level_4_option": opts["o4"],
            "level_5_point": opts["p5"], "level_5_option": opts["o5"],
            "level_6_point": opts["p6"], "level_6_option": opts["o6"],
        })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.ark_grid_cores_tb
            (character_name, slot_index, collected_at, name, grade, point, icon,
             level_1_point, level_1_option, level_2_point, level_2_option,
             level_3_point, level_3_option, level_4_point, level_4_option,
             level_5_point, level_5_option, level_6_point, level_6_option)
            VALUES (:character_name, :slot_index, :collected_at, :name, :grade, :point, :icon,
                    :level_1_point, :level_1_option, :level_2_point, :level_2_option,
                    :level_3_point, :level_3_option, :level_4_point, :level_4_option,
                    :level_5_point, :level_5_option, :level_6_point, :level_6_option)
        """), rows)


def _insert_ark_grid_gems(db, character_name, collected_at, api_data):
    ag = api_data.get("ArkGrid")
    if not ag:
        return

    rows = []
    for slot in ag.get("Slots") or []:
        core_idx = slot.get("Index")
        for gem in slot.get("Gems") or []:
            gem_eff_raw = parse_tooltip_content(gem.get("Tooltip"), "젬 효과")
            opts = split_gem_effect(gem_eff_raw)
            rows.append({
                "character_name": character_name,
                "core_index": core_idx,
                "gem_index": gem.get("Index"),
                "collected_at": collected_at,
                "grade": gem.get("Grade"),
                "is_active": gem.get("IsActive"),
                "icon": gem.get("Icon"),
                "required_willpower": opts["req_will"],
                "willpower_efficiency": opts["will_eff"],
                "point_type": opts["pt_type"],
                "point_value": opts["pt_val"],
                "effect_1_name": opts["e1_name"],
                "effect_1_level": opts["e1_lvl"],
                "effect_1_value": opts["e1_val"],
                "effect_2_name": opts["e2_name"],
                "effect_2_level": opts["e2_lvl"],
                "effect_2_value": opts["e2_val"],
            })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.ark_grid_gems_tb
            (character_name, core_index, gem_index, collected_at, grade, is_active, icon,
             required_willpower, willpower_efficiency, point_type, point_value,
             effect_1_name, effect_1_level, effect_1_value,
             effect_2_name, effect_2_level, effect_2_value)
            VALUES (:character_name, :core_index, :gem_index, :collected_at, :grade, :is_active, :icon,
                    :required_willpower, :willpower_efficiency, :point_type, :point_value,
                    :effect_1_name, :effect_1_level, :effect_1_value,
                    :effect_2_name, :effect_2_level, :effect_2_value)
        """), rows)


def _insert_ark_passive_points(db, character_name, collected_at, api_data):
    ap = api_data.get("ArkPassive") or {}
    points_data = ap.get("Points") or []
    if not points_data:
        return

    rows = []
    for p in points_data:
        rank_val, level_val = parse_rank_level(p.get("Description"))
        rows.append({
            "character_name": character_name,
            "name": p.get("Name"),
            "collected_at": collected_at,
            "value": p.get("Value"),
            "point_rank": rank_val,
            "point_level": level_val,
        })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.ark_passive_points_tb
            (character_name, name, collected_at, value, point_rank, point_level)
            VALUES (:character_name, :name, :collected_at, :value, :point_rank, :point_level)
        """), rows)


def _insert_ark_passive_effects(db, character_name, collected_at, api_data):
    ap = api_data.get("ArkPassive") or {}
    effects_data = ap.get("Effects") or []
    if not effects_data:
        return

    rows = []
    for e in effects_data:
        tier, effect_name, level = parse_ark_passive_description(e.get("Description"))
        rows.append({
            "character_name": character_name,
            "name": e.get("Name"),
            "collected_at": collected_at,
            "icon": e.get("Icon"),
            "tier": tier,
            "effect_name": effect_name,
            "level": level,
        })

    if rows:
        db.execute(text("""
            INSERT INTO lostark.ark_passive_effects_tb
            (character_name, name, collected_at, icon, tier, effect_name, level)
            VALUES (:character_name, :name, :collected_at, :icon, :tier, :effect_name, :level)
        """), rows)
