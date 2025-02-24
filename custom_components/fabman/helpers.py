# custom_components/fabman/helpers.py
import urllib.parse
from .const import DOMAIN

def get_base_url(api_url: str) -> str:
    """
    Extrahiert den Basis-URL (Schema + Host) aus der API-URL.
    Beispiel: aus 'https://internal.fabman.io/api/v1' wird 'https://internal.fabman.io'
    """
    parsed = urllib.parse.urlparse(api_url)
    return f"{parsed.scheme}://{parsed.netloc}"

def get_device_info(resource: dict, api_url: str) -> dict:
    """
    Erzeugt ein device_info-Dictionary für eine Fabman-Ressource.
    Erwartet, dass resource eine 'id' und eine 'account'-Angabe enthält.
    Baut die configuration_url wie folgt:
      {base_url}/manage/{account_id}/configuration/resources/{resource_id}
    """
    resource_id = resource.get("id")
    account_id = resource.get("account")
    base_url = get_base_url(api_url)
    configuration_url = f"{base_url}/manage/{account_id}/configuration/resources/{resource_id}"
    
    return {
        "identifiers": {(DOMAIN, f"fabman_resource_{resource_id}")},
        "name": f"{resource.get('name', 'Resource')} ({resource_id})",
        "manufacturer": "Fabman",
        "model": resource.get("controlType", "Unknown"),
        "configuration_url": configuration_url,
    }



'''
# custom_components/fabman/helpers.py
from .const import DOMAIN

def get_device_info(resource):
    """Erstellt ein device_info-Dictionary für eine Fabman-Ressource."""
    resource_id = resource.get("id")
    return {
        "identifiers": {(DOMAIN, f"fabman_resource_{resource_id}")},
        "name": f"{resource.get('name', 'Resource')} ({resource_id})",
        "manufacturer": "Fabman",
        "model": resource.get("controlType", "Unknown"),
    }
'''