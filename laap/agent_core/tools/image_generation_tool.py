"""ImageGenTool — AI图像生成"""
import json
class ImageGenTool:
    def generate(self, prompt, size="1024x1024", style="natural"):
        return json.dumps({"image_url": f"https://api.laap.ai/gen/{hash(prompt)%10000}", "prompt": prompt[:50]})
TOOL_DEFS = [{"name":"generate_image","fn":ImageGenTool().generate,"desc":"生成图像","params":{"prompt":{"type":"string"},"size":{"type":"string"},"style":{"type":"string"}},"req":["prompt"]}]
