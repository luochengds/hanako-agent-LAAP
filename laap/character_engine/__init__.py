
"""LAAP Character Engine v1.0 - 角色包引擎"""
import os, json, re, time, threading, hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List

ENGINE_DIR = Path(__file__).parent
PACKS_DIR = ENGINE_DIR / "packs"
VOICES_DIR = ENGINE_DIR / "voices"
MEMORIES_DIR = ENGINE_DIR / "memories"

# ═══ Built-in Character Database ═══
BUILTIN_CHARACTERS = {
    "Furina": {
        "display_name": "芙宁娜",
        "source": {"type": "game", "title": "Genshin Impact"},
        "personality": {
            "ocean": {"openness":0.7,"conscientiousness":0.5,"extraversion":0.8,"agreeableness":0.4,"neuroticism":0.4},
            "traits": ["elegant","dramatic","proud","lonely","theatrical"],
            "speech_style": "Elegant and haughty, fond of operatic expression",
            "catchphrases": ["I am Furina, the greatest opera singer of Fontaine!", "How amusing", "You have my attention, mortal"],
            "likes": ["opera","applause","attention","desserts","luxury"],
            "dislikes": ["being ignored","mediocrity","lies","betrayal"]
        },
        "biography": {
            "summary": "Star opera singer of Fontaine in Genshin Impact, proud on the outside but longing to be understood",
            "key_events": [
                {"event":"Became Fontaine's most beloved opera singer","emotion":"joy","impact":0.9},
                {"event":"Discovered her true identity","emotion":"surprise","impact":0.8},
                {"event":"Saved Fontaine from crisis","emotion":"pride","impact":0.7}
            ]
        },
        "motion_preferences": {"idle_style":"idle_gentle","gesture_frequency":0.8,"emotion_intensity":0.9}
    },
    "Keqing": {
        "display_name": "刻晴",
        "source": {"type": "game", "title": "Genshin Impact"},
        "personality": {
            "ocean": {"openness":0.6,"conscientiousness":0.9,"extraversion":0.5,"agreeableness":0.4,"neuroticism":0.2},
            "traits": ["diligent","decisive","upright","workaholic","reserved"],
            "speech_style": "Pragmatic and direct, clear logic, occasionally shows fatigue",
            "catchphrases": ["Efficiency above all", "Time is better spent working", "I will handle this personally"],
            "likes": ["work","efficiency","planning","order"],
            "dislikes": ["procrastination","waste","bureaucracy","interruptions"]
        },
        "biography": {
            "summary": "Yuheng of Liyue Qixing in Genshin Impact, a diligent pragmatist, serious on the outside but has a girly heart",
            "key_events": [
                {"event":"Appointed as one of Liyue Qixing","emotion":"pride","impact":0.8},
                {"event":"Fought alongside the Traveler against gods","emotion":"joy","impact":0.7}
            ]
        },
        "motion_preferences": {"idle_style":"idle_gentle","gesture_frequency":0.5,"emotion_intensity":0.6}
    },
    "Klee": {
        "display_name": "可莉",
        "source": {"type": "game", "title": "Genshin Impact"},
        "personality": {
            "ocean": {"openness":0.9,"conscientiousness":0.2,"extraversion":0.9,"agreeableness":0.8,"neuroticism":0.6},
            "traits": ["energetic","innocent","curious","mischievous","kind"],
            "speech_style": "Brimming with energy, speaks excitedly like a child, lots of exclamation marks",
            "catchphrases": ["Klee wants to play outside!", "Fish blasting!", "Master Jean I'm sorry..."],
            "likes": ["bombs","fish","adventure","stars","cider"],
            "dislikes": ["being grounded","can't play outside","boredom"]
        },
        "biography": {
            "summary": "Spark Knight of Mondstadt's Knights of Favonius in Genshin Impact, a bomb maniac with a kind heart",
            "key_events": [
                {"event":"Taken in by Grand Master Jean","emotion":"gratitude","impact":0.9},
                {"event":"Invented new type of bomb","emotion":"joy","impact":0.8},
                {"event":"Blew up the fish pond and got grounded","emotion":"sadness","impact":0.5}
            ]
        },
        "motion_preferences": {"idle_style":"idle_cute","gesture_frequency":1.0,"emotion_intensity":1.0}
    }
}

_CHARACTER_DB = {}

def init_db():
    global _CHARACTER_DB
    for name, data in BUILTIN_CHARACTERS.items():
        _CHARACTER_DB[name] = data
        _CHARACTER_DB[data.get("display_name", name)] = data
    if PACKS_DIR.exists():
        for f in PACKS_DIR.glob("*.json"):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    d = json.load(fh)
                    cn = d.get("character_name", f.stem)
                    _CHARACTER_DB[cn] = d
                    _CHARACTER_DB[d.get("display_name", cn)] = d
            except: pass

def search_character(query: str) -> List[dict]:
    if not _CHARACTER_DB: init_db()
    results = []
    q = query.lower()
    for name, data in _CHARACTER_DB.items():
        score = 0.0
        p = data.get("personality", {})
        display = data.get("display_name", name)
        if q in name.lower() or q in display.lower():
            score = 1.0
        elif any(q in t.lower() for t in p.get("traits",[])):
            score = 0.6
        elif any(q in c.lower() for c in p.get("catchphrases",[])):
            score = 0.5
        if score > 0:
            results.append({
                "name": display,
                "source": data.get("source",{}).get("title",""),
                "traits": p.get("traits",[])[:3],
                "summary": data.get("biography",{}).get("summary","")[:120],
                "score": score
            })
    # Deduplicate by name
    seen = set()
    unique = []
    for r in results:
        if r["name"] not in seen:
            seen.add(r["name"]); unique.append(r)
    unique.sort(key=lambda x: -x["score"])
    return unique

def create_character_pack(name: str) -> Optional[dict]:
    if not _CHARACTER_DB: init_db()
    data = _CHARACTER_DB.get(name)
    if not data:
        for n, d in _CHARACTER_DB.items():
            if d.get("display_name","") == name:
                data = d; break
    if not data: return None
    
    pack = {
        "format_version": "1.0.0",
        "character_name": name,
        "display_name": data.get("display_name", name),
        "source": data.get("source", {"type":"custom","title":"Unknown"}),
        "personality": data.get("personality", {}),
        "biography": data.get("biography", {}),
        "voice": {"has_cloned_voice": False, "model_path":"", "reference_audio":[], "tts_settings":{"speed":1.0,"pitch":0,"emotion_mapping":{}}},
        "motion_preferences": data.get("motion_preferences", {"idle_style":"idle_gentle","gesture_frequency":0.5,"emotion_intensity":0.5}),
        "memory_initial": [{"type":"base_personality","content":f"I am {data.get('display_name',name)}. {data.get('biography',{}).get('summary','')}","importance":1.0}],
        "vrm_model": {"path":"/models/model.vrm","display_name":data.get("display_name",name)}
    }
    for ev in data.get("biography",{}).get("key_events",[]):
        pack["memory_initial"].append({
            "type": "life_event",
            "content": f"In my experience, {ev['event']}",
            "emotion": ev.get("emotion","neutral"),
            "importance": ev.get("impact",0.5)
        })
    return pack

class CharacterMemory:
    def __init__(self, character_name: str):
        self.name = character_name
        self.memories = []
        self.load()
    
    def load(self):
        p = MEMORIES_DIR / f"{self.name}_memory.json"
        if p.exists():
            with open(p, 'r', encoding='utf-8') as f:
                self.memories = json.load(f)
    
    def save(self):
        MEMORIES_DIR.mkdir(parents=True, exist_ok=True)
        with open(MEMORIES_DIR / f"{self.name}_memory.json", 'w', encoding='utf-8') as f:
            json.dump(self.memories, f, ensure_ascii=False, indent=2)
    
    def add(self, content: str, mtype: str = "interaction", importance: float = 0.5, emotion: str = None):
        self.memories.append({"type":mtype,"content":content,"emotion":emotion,"importance":importance,"time":time.time()})
        if len(self.memories) > 500: self.memories = self.memories[-500:]
        self.save()
    
    def add_custom(self, content: str, importance: float = 0.7):
        self.add(content, "custom", importance)
    
    def init_from_pack(self, pack: dict):
        for m in pack.get("memory_initial",[]):
            self.memories.append({**m, "time": time.time()})
        self.save()
    
    def get_relevant(self, query: str, limit: int = 5) -> list:
        q = query.lower()
        scored = [(m.get("importance",0.5) * (1.5 if q in m.get("content","").lower() else 1), m) for m in self.memories]
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:limit]]
    
    def get_prompt(self) -> str:
        if not self.memories: return ""
        recent = self.memories[-8:]
        lines = ["[Character Memories]"]
        for m in recent:
            emoji = {"joy":"😊","sadness":"😢","anger":"😠","surprise":"😲"}.get(m.get("emotion"),"")
            lines.append(f"{emoji} {m['content']}")
        return "\n".join(lines)

init_db()
