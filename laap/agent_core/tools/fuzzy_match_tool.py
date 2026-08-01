"""FuzzyMatchTool — 模糊匹配"""
import json
class FuzzyMatchTool:
    def match(self, query, candidates, threshold=0.6):
        results = []
        for c in candidates:
            common = sum(1 for a,b in zip(query.lower(), c.lower()) if a==b)
            score = common / max(len(query), len(c), 1)
            if score >= threshold:
                results.append({"candidate": c, "score": round(score, 2)})
        return json.dumps(sorted(results, key=lambda x:-x["score"])[:10])
TOOL_DEFS = [{"name":"fuzzy_match","fn":FuzzyMatchTool().match,"desc":"模糊匹配","params":{"query":{"type":"string"},"candidates":{"type":"array"},"threshold":{"type":"number"}},"req":["query","candidates"]}]
