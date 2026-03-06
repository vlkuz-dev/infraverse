"""External URL link builder for Infraverse detail pages."""

from __future__ import annotations


def render_url(template: str | None, data: dict) -> str | None:
    """Render a URL template with data.

    Returns None if template is None/empty or if any placeholder
    cannot be filled from the data dict.
    """
    if not template:
        return None
    try:
        url = template.format_map(data)
    except (KeyError, ValueError):
        return None
    # If any unfilled placeholders remain, return None
    if "{" in url:
        return None
    # If any placeholder resolved to empty string, return None
    for value in data.values():
        if value == "":
            return None
    return url


def build_vm_links(vm_data: dict, account_data: dict | None, config) -> list[dict]:
    """Build external links for a VM detail page.

    Returns a list of dicts with 'label', 'url', and 'icon' keys.
    Only includes links where all required data is available.
    """
    links = []

    if config is None:
        return links

    account_config = {}
    if account_data:
        account_config = account_data.get("config") or {}

    # Yandex Cloud Console
    yc_data = {
        "folder_id": account_config.get("folder_id", ""),
        "vm_id": vm_data.get("external_id", ""),
    }
    yc_url = render_url(config.yc_console_url, yc_data)
    if yc_url:
        links.append({"label": "Cloud Console", "url": yc_url, "icon": "cloud"})

    # Zabbix host
    zabbix_data = {
        "zabbix_url": (config.zabbix_url or "").rstrip("/"),
        "host_id": vm_data.get("monitoring_host_id", ""),
    }
    zabbix_url = render_url(config.zabbix_host_url, zabbix_data)
    if zabbix_url:
        links.append({"label": "Zabbix", "url": zabbix_url, "icon": "activity"})

    # NetBox VM
    netbox_data = {
        "netbox_url": (config.netbox_url or "").rstrip("/"),
        "vm_id": vm_data.get("external_id", ""),
    }
    netbox_url = render_url(config.netbox_vm_url, netbox_data)
    if netbox_url:
        links.append({"label": "NetBox", "url": netbox_url, "icon": "server"})

    return links


def build_account_links(account_data: dict, config) -> list[dict]:
    """Build external links for a cloud account detail page.

    Returns a list of dicts with 'label', 'url', and 'icon' keys.
    """
    links = []

    if config is None:
        return links

    account_config = account_data.get("config") or {}

    # Yandex Cloud Console folder link
    if account_data.get("provider_type") == "yandex_cloud":
        folder_id = account_config.get("folder_id", "")
        if folder_id and config.yc_console_url:
            # Derive folder-level URL from the VM URL template
            # by using only the folder part
            folder_url = render_url(
                "https://console.yandex.cloud/folders/{folder_id}",
                {"folder_id": folder_id},
            )
            if folder_url:
                links.append({"label": "Cloud Console", "url": folder_url, "icon": "cloud"})

    return links
