import json
import re
import unicodedata

import requests


DESTINATIONS_URL = "https://api.themeparks.wiki/v1/destinations"
LIVE_URL = "https://api.themeparks.wiki/v1/entity/{entity_id}/live"
USER_AGENT = "ParkSignals/1.0"
ATTRACTION_ENTITY_TYPES = {"ATTRACTION", "SHOW", "RESTAURANT"}
OPEN_STATUSES = {"OPERATING"}
PLANNED_CLOSURE_STATUSES = {"REFURBISHMENT"}
UNAVAILABLE_STATUSES = {"DOWN", "CLOSED"}
WDW_DESTINATION_MATCH = "walt disney world"
PARK_NAME_MATCHES = {
    "magic_kingdom": ["magic kingdom"],
    "epcot": ["epcot"],
    "hollywood_studios": ["hollywood studios"],
    "animal_kingdom": ["animal kingdom"],
}


def get_json(url):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    return response.json()


def find_destinations_list(payload):
    if isinstance(payload, list):
        return payload
    for key in ("destinations", "data"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def iter_entities(entity):
    yield entity
    for child_key in ("parks", "children", "entities"):
        for child in entity.get(child_key, []) or []:
            yield from iter_entities(child)


def find_wdw_destination(destinations):
    for destination in destinations:
        name = str(destination.get("name", "")).lower()
        if WDW_DESTINATION_MATCH in name:
            return destination
    return None


def match_park_entity(park_key, destinations_payload=None):
    if destinations_payload is None:
        destinations_payload = get_json(DESTINATIONS_URL)
    destination = find_wdw_destination(find_destinations_list(destinations_payload))
    if not destination:
        raise RuntimeError("ThemeParks Wiki Walt Disney World destination not found")

    matches = PARK_NAME_MATCHES[park_key]
    for entity in iter_entities(destination):
        entity_type = str(entity.get("entityType") or entity.get("type") or "").lower()
        name = str(entity.get("name", "")).lower()
        if entity_type and "park" not in entity_type:
            continue
        if any(match in name for match in matches):
            return entity
    return None


def normalize_name(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.replace("&", "and")
    value = value.replace("™", "")
    value = value.replace("'", "")
    value = value.replace("’", "")
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value).strip().lower()
    return re.sub(r"\s+", " ", value)


def configured_ride_names(park_config):
    names = []
    for ride in park_config.get("major_rides", []):
        if isinstance(ride, str):
            names.append(ride)
        elif isinstance(ride, dict) and ride.get("name"):
            names.append(ride["name"])
    return names


def configured_aliases(park_config, ride_name):
    aliases = [ride_name]
    alias_map = park_config.get("ride_name_aliases", {})
    aliases.extend(alias_map.get(ride_name, []))
    for ride in park_config.get("major_rides", []):
        if isinstance(ride, dict) and ride.get("name") == ride_name:
            aliases.extend(ride.get("aliases", []))
            if ride.get("themeparks_wiki_name"):
                aliases.append(ride["themeparks_wiki_name"])
    return aliases


def extract_wait_time(live_item):
    queue = live_item.get("queue") or {}
    standby = queue.get("STANDBY") or queue.get("standby") or {}
    wait_time = standby.get("waitTime")
    return wait_time if isinstance(wait_time, int) else None


def status_to_is_open(status):
    if status in OPEN_STATUSES:
        return True
    if status in PLANNED_CLOSURE_STATUSES:
        return False
    if status in UNAVAILABLE_STATUSES:
        return False
    return None


def planned_closure_from_status(status, live_item):
    if status not in PLANNED_CLOSURE_STATUSES:
        return None
    return {
        "ride_name": live_item.get("name"),
        "starts_on": None,
        "ends_on": None,
        "reason": "refurbishment",
        "source": "themeparks_wiki_live_status",
        "status": status,
    }


def live_items(payload):
    items = payload.get("liveData") or payload.get("data") or []
    return items if isinstance(items, list) else []


def attraction_items(payload):
    items = []
    for item in live_items(payload):
        entity_type = str(item.get("entityType") or item.get("type") or "").upper()
        if entity_type in ATTRACTION_ENTITY_TYPES or not entity_type:
            items.append(item)
    return items


def match_live_item(ride_name, park_config, live_by_normalized_name):
    for alias in configured_aliases(park_config, ride_name):
        normalized = normalize_name(alias)
        if normalized in live_by_normalized_name:
            return live_by_normalized_name[normalized], alias
    return None, None


def fetch_live_payload(park_key, park_config):
    entity_id = park_config.get("themeparks_wiki_entity_id")
    entity_name = park_config.get("themeparks_wiki_entity_name")
    if not entity_id:
        entity = match_park_entity(park_key)
        if not entity or not entity.get("id"):
            raise RuntimeError(f"ThemeParks Wiki park entity not found for {park_key}")
        entity_id = entity["id"]
        entity_name = entity.get("name")
    payload = get_json(LIVE_URL.format(entity_id=entity_id))
    return entity_id, entity_name, payload


def fetch_rides(park_key, park_config):
    entity_id, entity_name, payload = fetch_live_payload(park_key, park_config)
    live_by_normalized_name = {
        normalize_name(item.get("name")): item
        for item in attraction_items(payload)
        if item.get("name")
    }
    rides = []
    missing = []
    for ride_name in configured_ride_names(park_config):
        item, matched_alias = match_live_item(ride_name, park_config, live_by_normalized_name)
        if not item:
            missing.append(ride_name)
            continue
        status = item.get("status")
        rides.append({
            "id": str(item.get("id")),
            "name": ride_name,
            "source_name": item.get("name"),
            "is_open": status_to_is_open(status),
            "wait_time": extract_wait_time(item),
            "source": "themeparks_wiki",
            "source_status": status,
            "source_entity_id": item.get("id"),
            "matched_alias": matched_alias,
            "planned_closure": planned_closure_from_status(status, item),
            "last_updated": item.get("lastUpdated"),
        })
    if missing:
        available = sorted(item.get("name", "") for item in attraction_items(payload) if item.get("name"))
        raise RuntimeError(
            "ThemeParks Wiki ride mapping incomplete for "
            + park_config.get("park_name", park_key)
            + ": missing "
            + json.dumps(missing)
            + "; available names include "
            + json.dumps(available[:40])
        )
    return rides


def validate_mapping(config):
    results = []
    for park_key, park_config in config.get("parks", {}).items():
        if not park_config.get("enabled", False):
            continue
        try:
            entity_id, entity_name, payload = fetch_live_payload(park_key, park_config)
            live_by_normalized_name = {
                normalize_name(item.get("name")): item
                for item in attraction_items(payload)
                if item.get("name")
            }
            matches = []
            missing = []
            for ride_name in configured_ride_names(park_config):
                item, matched_alias = match_live_item(ride_name, park_config, live_by_normalized_name)
                if item:
                    matches.append({
                        "configured_name": ride_name,
                        "matched_name": item.get("name"),
                        "matched_alias": matched_alias,
                        "entity_id": item.get("id"),
                        "status": item.get("status"),
                        "wait_time": extract_wait_time(item),
                    })
                else:
                    missing.append(ride_name)
            results.append({
                "park_key": park_key,
                "park_name": park_config.get("park_name"),
                "themeparks_wiki_entity_id": entity_id,
                "themeparks_wiki_entity_name": entity_name or payload.get("name"),
                "configured_count": len(configured_ride_names(park_config)),
                "matched_count": len(matches),
                "missing_count": len(missing),
                "matches": matches,
                "missing": missing,
            })
        except Exception as exc:
            results.append({
                "park_key": park_key,
                "park_name": park_config.get("park_name"),
                "error": str(exc),
            })
    return results
