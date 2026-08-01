"""CredentialSources — 凭据源"""
import os, json
from typing import Dict, List, Optional

class CredentialSources:
    SOURCES = ["env", "file", "keychain"]
    def get(self, key: str) -> Optional[str]:
        val = os.environ.get(f"LAAP_{key.upper()}")
        if val:
            return val
        cfg_path = os.path.expanduser("~/.laap/credentials.json")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path) as f:
                    return json.load(f).get(key)
            except: pass
        return None
    def list_keys(self) -> List[str]:
        keys = [k.replace("LAAP_","").lower() for k in os.environ if k.startswith("LAAP_")]
        cfg_path = os.path.expanduser("~/.laap/credentials.json")
        if os.path.exists(cfg_path):
            try:
                keys.extend(json.load(open(cfg_path)).keys())
            except: pass
        return list(set(keys))
