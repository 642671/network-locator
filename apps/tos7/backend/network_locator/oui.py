"""Small, offline OUI vendor table and MAC classification helpers.

The table intentionally covers common LAN vendors instead of shipping the full
IEEE registry. Unknown prefixes are reported as an empty string so the UI can
say "unknown vendor" honestly instead of guessing.
"""

from __future__ import annotations

import re
from typing import Iterable

_VENDORS: dict[str, str] = {
    "000C29": "VMware",
    "000569": "VMware",
    "001C14": "VMware",
    "005056": "VMware",
    "0A0027": "VirtualBox",
    "080027": "VirtualBox",
    "00155D": "Microsoft Hyper-V",
    "001C42": "Parallels",
    "00163E": "Xensource",
    "525400": "QEMU/KVM",
    "000347": "Intel",
    "000E0C": "Intel",
    "001B21": "Intel",
    "001E64": "Intel",
    "0021CC": "Intel",
    "0024D7": "Intel",
    "0026C7": "Intel",
    "3C9509": "Intel",
    "4851B7": "Intel",
    "5CE0C5": "Intel",
    "7CB27D": "Intel",
    "8C1645": "Intel",
    "9CB6D0": "Intel",
    "A0A8CD": "Intel",
    "B49691": "Intel",
    "E4A471": "Intel",
    "F8E43B": "Intel",
    "000393": "Apple",
    "001124": "Apple",
    "001451": "Apple",
    "0017F2": "Apple",
    "0019E3": "Apple",
    "001B63": "Apple",
    "0021E9": "Apple",
    "002332": "Apple",
    "00236C": "Apple",
    "002500": "Apple",
    "0026B0": "Apple",
    "3C0754": "Apple",
    "40A6D9": "Apple",
    "5C95AE": "Apple",
    "6C709F": "Apple",
    "78CA39": "Apple",
    "8C8590": "Apple",
    "9C04EB": "Apple",
    "A4C361": "Apple",
    "ACBC32": "Apple",
    "B8E856": "Apple",
    "D0E140": "Apple",
    "DC2B2A": "Apple",
    "F0DBF8": "Apple",
    "F4F15A": "Apple",
    "0015B9": "Samsung",
    "0017C9": "Samsung",
    "001A8A": "Samsung",
    "0021D1": "Samsung",
    "002454": "Samsung",
    "0026E2": "Samsung",
    "0C715D": "Samsung",
    "34AA8B": "Samsung",
    "38D40B": "Samsung",
    "4C3C16": "Samsung",
    "5C0A5B": "Samsung",
    "78A873": "Samsung",
    "8C7712": "Samsung",
    "A0CB8B": "Samsung",
    "B0DF3A": "Samsung",
    "D0176A": "Samsung",
    "E8E5D6": "Samsung",
    "0018FE": "HP",
    "001A4B": "HP",
    "0025B3": "HP",
    "3C4A92": "HP",
    "6CC217": "HP",
    "9457A5": "HP",
    "B499BA": "HP",
    "D48564": "HP",
    "0012FE": "Cisco",
    "0017DF": "Cisco",
    "001A2F": "Cisco",
    "001B0C": "Cisco",
    "0021A0": "Cisco",
    "0023EB": "Cisco",
    "0026CB": "Cisco",
    "3C0E23": "Cisco",
    "58BC27": "Cisco",
    "6C416A": "Cisco",
    "0019E0": "TP-Link",
    "0023CD": "TP-Link",
    "14CC20": "TP-Link",
    "1C3BF3": "TP-Link",
    "30B5C2": "TP-Link",
    "50C7BF": "TP-Link",
    "6032B1": "TP-Link",
    "94D9B3": "TP-Link",
    "B0BE76": "TP-Link",
    "C46E1F": "TP-Link",
    "F4F26D": "TP-Link",
    "000D88": "D-Link",
    "001195": "D-Link",
    "0015E9": "D-Link",
    "001CF0": "D-Link",
    "0022B0": "D-Link",
    "0024B2": "D-Link",
    "1CBDB9": "D-Link",
    "3C1E04": "D-Link",
    "78286F": "D-Link",
    "000FB5": "NETGEAR",
    "001B2F": "NETGEAR",
    "0022B5": "NETGEAR",
    "20E52A": "NETGEAR",
    "2C3033": "NETGEAR",
    "44944A": "NETGEAR",
    "9C3DCF": "NETGEAR",
    "A00460": "NETGEAR",
    "C03F0E": "NETGEAR",
    "E0469A": "NETGEAR",
    "00248C": "ASUS",
    "1C872C": "ASUS",
    "2C56DC": "ASUS",
    "38D547": "ASUS",
    "50465D": "ASUS",
    "AC220B": "ASUS",
    "D017C2": "ASUS",
    "F832E4": "ASUS",
    "001A11": "Google",
    "3C5AB4": "Google",
    "546009": "Google",
    "6C1C71": "Google",
    "94EB2C": "Google",
    "A4DA22": "Google",
    "F4F5D8": "Google",
    "0017D1": "QNAP",
    "245EBE": "QNAP",
    "00089B": "Synology",
    "001132": "Synology",
    "9009D0": "Synology",
    "001A79": "Dell",
    "001EC9": "Dell",
    "002219": "Dell",
    "0025B5": "Dell",
    "14FEB5": "Dell",
    "18DBF2": "Dell",
    "3417EB": "Dell",
    "54BF64": "Dell",
    "78DB2F": "Dell",
    "B8CA3A": "Dell",
    "001CC4": "HPE",
    "001F29": "HPE",
    "0009BF": "Nintendo",
    "0017AB": "Nintendo",
    "0024F3": "Nintendo",
    "78A2A0": "Nintendo",
    "98348C": "Nintendo",
    "001A7D": "Sony",
    "0024BE": "Sony",
    "3C0771": "Sony",
    "544249": "Sony",
    "78C881": "Sony",
    "0018DD": "Silicondust",
    "001195": "D-Link",
    "000E8F": "Sercomm",
    "8CBEBE": "Xiaomi",
    "286C07": "Xiaomi",
    "64B473": "Xiaomi",
    "F0B429": "Xiaomi",
    "7C1DD9": "Xiaomi",
    "34CE00": "Xiaomi",
    "50EC50": "Xiaomi",
    "78110F": "Xiaomi",
    "949F3E": "Xiaomi",
    "F8A45F": "Xiaomi",
    "0018B8": "Huawei",
    "00259E": "Huawei",
    "0022A1": "Huawei",
    "00E0FC": "Huawei",
    "04BD70": "Huawei",
    "0C37DC": "Huawei",
    "20F3A3": "Huawei",
    "3CDFBD": "Huawei",
    "48DB50": "Huawei",
    "5C7D5E": "Huawei",
    "78D752": "Huawei",
    "9C28EF": "Huawei",
    "AC853D": "Huawei",
    "D02DB3": "Huawei",
    "F4C714": "Huawei",
    "0017EE": "Realtek",
    "00E04C": "Realtek",
    "52544C": "Realtek",
    "24F5A2": "Espressif",
    "240AC4": "Espressif",
    "3C71BF": "Espressif",
    "5CCF7F": "Espressif",
    "84F3EB": "Espressif",
    "A020A6": "Espressif",
    "B4E62D": "Espressif",
    "CC50E3": "Espressif",
    "DC4F22": "Espressif",
    "ECFA5C": "Espressif",
    "001D0F": "Broadcom",
    "00408C": "Broadcom",
    "B827EB": "Raspberry Pi",
    "DCA632": "Raspberry Pi",
    "E45F01": "Raspberry Pi",
    "2CCF67": "Raspberry Pi",
}

_PREFIX_ALIASES = {
    "VMWARE": ["000C29", "000569", "001C14", "005056"],
    "APPLE": ["000393", "001124", "3C0754", "8C8590", "F4F15A"],
    "SAMSUNG": ["0015B9", "002454", "4C3C16", "8C7712"],
    "INTEL": ["000347", "001B21", "3C9509", "8C1645"],
    "TP-LINK": ["0019E0", "50C7BF", "94D9B3", "F4F26D"],
    "XIAOMI": ["286C07", "64B473", "78110F", "8CBEBE"],
    "HUAWEI": ["0018B8", "00259E", "48DB50", "AC853D"],
    "ESPRESSIF": ["24F5A2", "3C71BF", "84F3EB", "DC4F22"],
}


def normalize_mac(value: object) -> str:
    """Return ``AA-BB-CC-DD-EE-FF`` or an empty string."""

    compact = re.sub(r"[^0-9A-Fa-f]", "", str(value or ""))
    if len(compact) != 12:
        return ""
    compact = compact.upper()
    return "-".join(compact[index : index + 2] for index in range(0, 12, 2))


def mac_compact(value: object) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).upper()


def oui_prefix(value: object) -> str:
    compact = mac_compact(value)
    return compact[:6] if len(compact) >= 6 else ""


def vendor_for_mac(value: object) -> str:
    return _VENDORS.get(oui_prefix(value), "")


def mac_kind(value: object) -> str:
    """Classify a MAC as unicast/multicast and universal/local (random)."""

    compact = mac_compact(value)
    if len(compact) != 12:
        return "invalid"
    first = int(compact[:2], 16)
    if first & 0x01:
        return "multicast"
    if first & 0x02:
        return "local"
    return "universal"


def prefixes_for_name(name: str) -> list[str]:
    return list(_PREFIX_ALIASES.get(str(name or "").upper(), []))


def lookup_vendor_prefixes(value: object) -> list[dict]:
    """Return vendor entries whose OUI prefixes contain the query prefix."""

    prefix = mac_compact(value)
    if not prefix:
        return []
    return [
        {"prefix": item, "vendor": vendor}
        for item, vendor in sorted(_VENDORS.items())
        if item.startswith(prefix)
    ][:50]


def vendor_count() -> int:
    return len(_VENDORS)


def classify_query(value: object) -> tuple[str, str]:
    """Classify a MAC query as full/prefix/suffix/any and normalize its hex."""

    compact = mac_compact(value)
    if not compact:
        return "invalid", ""
    if len(compact) == 12:
        return "full", compact
    if len(compact) == 6:
        return "prefix", compact
    if len(compact) == 4:
        return "suffix", compact
    if len(compact) < 6:
        return "suffix", compact
    return "any", compact