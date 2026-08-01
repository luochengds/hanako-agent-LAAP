"""UrlSafetyTool — URL安全检查"""
import json, re
class UrlSafetyTool:
    THREATS = [r"phish", r"malware", r"evil", r"hack"]
    def check(self, url):
        threats = [p for p in self.THREATS if re.search(p, url.lower())]
        return json.dumps({"url": url, "safe": len(threats)==0, "threats": threats})
TOOL_DEFS = [{"name":"check_url_safety","fn":UrlSafetyTool().check,"desc":"URL安全检查","params":{"url":{"type":"string"}},"req":["url"]}]
