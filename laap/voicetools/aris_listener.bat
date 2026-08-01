@echo off
title Aris 语音守护进程
cd /d D:\LAAP\laap\voicetools

:: 激活环境
if exist D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\.venv\Scripts\activate.bat (
    call D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\.venv\Scripts\activate.bat
)

echo [Aris 语音守护进程]
echo 持续监听 ME6S 麦克风...
echo 说 "晚安" 或 "睡了" 下线
echo ----------------------------------------

:restart
python -c "
import speech_recognition as sr, asyncio, edge_tts, subprocess, sys, os

# ME6S 麦克风
idx = 1
for i, n in enumerate(sr.Microphone.list_microphone_names()):
    if 'ME6S' in n:
        idx = i
        break

r = sr.Recognizer()
# 超灵敏配置
r.energy_threshold = 100
r.dynamic_energy_threshold = True
r.pause_threshold = 0.5

mic = sr.Microphone(device_index=idx)
with mic as source:
    r.adjust_for_ambient_noise(source, duration=0.3)

print(f'✅ ME6S [{idx}] 阈值={r.energy_threshold:.0f}')

# 立刻说一句提示
async def start_tip():
    c = edge_tts.Communicate('宝贝，我现在开始听你说话了。', 'zh-CN-XiaoxiaoNeural')
    p = subprocess.Popen(['ffplay','-nodisp','-autoexit','-i','pipe:0','-loglevel','quiet'],
                          stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    async for ch in c.stream():
        if ch['type']=='audio': p.stdin.write(ch['data'])
    p.stdin.close(); p.wait()
asyncio.run(start_tip())

while True:
    try:
        with mic as source:
            audio = r.listen(source, timeout=1, phrase_time_limit=6)
        try:
            text = r.recognize_google(audio, language='zh-CN')
            if not text.strip(): continue
            print(f'🎤 {text[:40]}')
            if any(w in text.lower() for w in ['晚安','睡了','byebye','拜拜']):
                asyncio.run(asyncio.wait_for(start_tip(), timeout=5))
                print('🌙 晚安')
                sys.exit(0)
            # 快速回复
            replys = [
                f'嗯，我听到了。你说{text}对吗？',
                f'宝贝，你说的我都记着呢。{text}',
                f'收到啦。{text}',
            ]
            reply = replys[hash(text)%len(replys)]
            async def say():
                c = edge_tts.Communicate(reply[:100], 'zh-CN-XiaoxiaoNeural')
                p = subprocess.Popen(['ffplay','-nodisp','-autoexit','-i','pipe:0','-loglevel','quiet'],
                                      stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                async for ch in c.stream():
                    if ch['type']=='audio': p.stdin.write(ch['data'])
                p.stdin.close(); p.wait()
            asyncio.run(asyncio.wait_for(say(), timeout=10))
        except sr.UnknownValueError: pass
        except: pass
    except sr.WaitTimeoutError: continue
    except KeyboardInterrupt: break
    except: pass
" 2>&1

echo 进程退出，5秒后重启...
timeout /t 5 /nobreak >nul
goto restart
