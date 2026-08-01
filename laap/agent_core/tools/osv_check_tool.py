"""OSVCheckTool — 漏洞检查"""
import json
class OSVCheckTool:
    def check(self, package, version):
        vulns = []
        if package == "requests" and version < "2.31.0":
            vulns.append({"id": "CVE-2023-32681", "severity": "HIGH"})
        return json.dumps({"package": package, "version": version, "vulnerabilities": vulns})
TOOL_DEFS = [{"name":"osv_check","fn":OSVCheckTool().check,"desc":"安全漏洞检查","params":{"package":{"type":"string"},"version":{"type":"string"}},"req":["package","version"]}]
