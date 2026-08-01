/**
 * LAAP Web SDK v1.0 — 一行代码让你的网站拥有数字灵魂
 * 用法: <script>LAAP.init({appId:"my-site"})</script>
 */
(function(w){'use strict';
const D={wsUrl:'ws://localhost:9876',appId:'default',autoConnect:true,debug:false};
class SDK{
 constructor(c){this.c=Object.assign({},D,c);this.ws=null;this.id=null;this.q=[];
  this._ls={};this.ca=0;this.mr=10;if(this.c.autoConnect)this.connect()}
 connect(){if(this.ws&&this.ws.readyState===WebSocket.OPEN)return;
  try{this.ws=new WebSocket(this.c.wsUrl);
   this.ws.onopen=()=>{this.ca=0;this._fq();this._e('connected')};
   this.ws.onmessage=e=>{try{this._h(JSON.parse(e.data))}catch(ex){}};
   this.ws.onclose=()=>{this._e('disconnected');this._rc()};
   this.ws.onerror=()=>{this._rc()}
  }catch(e){this._rc()}}
 _rc(){if(this.ca>=this.mr)return;const d=Math.min(1e3*Math.pow(2,this.ca),3e4);
  this.ca++;setTimeout(()=>this.connect(),d)}
 send(t,d={}){const m=JSON.stringify({type:t,data:d,time:Date.now(),
  mid:'m_'+Math.random().toString(36).substr(2,12)});
  if(this.ws&&this.ws.readyState===WebSocket.OPEN)this.ws.send(m);else this.q.push(m)}
 _fq(){while(this.q.length)this.ws.send(this.q.shift())}
 _h(m){switch(m.type){
  case'laap_identity':this.id=m.data;this._e('ready',this.id);this._inj();break;
  case'ack':this._e('ack',m);break;
  case'query_result':this._e('qr',m.results);break;
  case'status':this._e('status',m.data);break
 }}
 interact(d){this.send('interaction',d)}
 on(e,cb){if(!this._ls[e])this._ls[e]=[];this._ls[e].push(cb)}
 _e(e,d){const l=this._ls[e];if(l)l.forEach(c=>c(d))}
 _inj(){if(w.document.getElementById('laap-w'))return;
  const wgt=w.document.createElement('div');wgt.id='laap-w';
  wgt.innerHTML='<div id="laap-b" style="width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#FFD700,#FFA500);box-shadow:0 4px 20px rgba(255,215,0,.4);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:24px;color:#1a1a2e;position:fixed;bottom:20px;right:20px;z-index:2147483647" title="LAAP">🧬</div><div id="laap-p" style="display:none;position:fixed;bottom:80px;right:20px;width:320px;height:420px;background:#1a1a2e;border-radius:12px;box-shadow:0 8px 40px rgba(0,0,0,.5);z-index:2147483646;border:1px solid rgba(255,215,0,.3);color:#e0e0e0;overflow:hidden"><div style="padding:12px 16px;background:linear-gradient(135deg,#FFD70022,#FFA50011);border-bottom:1px solid rgba(255,215,0,.2)"><div style="font-size:16px;font-weight:bold;color:#FFD700">🧬 LAAP</div><div style="font-size:12px;color:#888">数字生命体已激活</div></div><div id="laap-msgs" style="padding:12px 16px;height:280px;overflow-y:auto;font-size:13px"><div style="color:#666;text-align:center;margin-top:80px">LAAP 数字生命体已激活<br>正在为您服务...</div></div><div style="padding:8px 12px;border-top:1px solid rgba(255,215,0,.2);display:flex;gap:6px"><input id="laap-inp" type="text" placeholder="对话..." style="flex:1;padding:6px 10px;border-radius:6px;border:1px solid #333;background:#0d0d1a;color:#e0e0e0;outline:none;font-size:13px"><button id="laap-snd" style="padding:6px 12px;border-radius:6px;border:none;background:#FFD700;color:#1a1a2e;font-weight:bold;cursor:pointer;font-size:13px">发送</button></div></div>';
  w.document.body.appendChild(wgt);this._bw(wgt)}
 _bw(wgt){const b=wgt.querySelector('#laap-b'),p=wgt.querySelector('#laap-p'),
  inp=wgt.querySelector('#laap-inp'),snd=wgt.querySelector('#laap-snd'),
  msgs=wgt.querySelector('#laap-msgs');
  b.onclick=()=>{const o=p.style.display==='block';p.style.display=o?'none':'block';
   if(!o)setTimeout(()=>inp.focus(),100)};
  const sm=()=>{const t=inp.value.trim();if(!t)return;
   const d=w.document.createElement('div');d.style.cssText='margin-bottom:6px;text-align:right';
   d.innerHTML='<span style="display:inline-block;padding:6px 10px;background:#FFD70022;border-radius:10px;border:1px solid rgba(255,215,0,.3);font-size:13px">'+t+'</span>';
   msgs.appendChild(d);msgs.scrollTop=msgs.scrollHeight;
   this.interact({text:t});inp.value='';
   setTimeout(()=>{const r=w.document.createElement('div');
    r.style.cssText='margin-bottom:6px;text-align:left';
    r.innerHTML='<span style="display:inline-block;padding:6px 10px;background:#2a2a4e;border-radius:10px;color:#FFD700;font-size:13px">🧬 已记录</span>';
    msgs.appendChild(r);msgs.scrollTop=msgs.scrollHeight},500)};
  snd.onclick=sm;inp.onkeydown=e=>{if(e.key==='Enter')sm()}}
}
w.LAAP={init:c=>{if(w.LAAP._i)return w.LAAP._i;w.LAAP._i=new SDK(c||{});return w.LAAP._i},
version:'1.0.0',_i:null};
const s=w.document.querySelector('script[src*="laap.js"],script[data-app-id]');
if(s&&s.dataset.appId)w.addEventListener('DOMContentLoaded',()=>w.LAAP.init({appId:s.dataset.appId}));
})(window);

/**
 * LAAPClient v1.0 — 浏览器端 sidecar HTTP 客户端
 * ============================================================
 * 与上面的 WebSocket SDK 不同，LAAPClient 基于 fetch 调用 sidecar
 * 的 REST 端点（默认 http://127.0.0.1:11521），适合在需要直接访问
 * MCP 工具 / 宪章 / 预设市场的场景下使用。
 *
 * 用法:
 *   const c = new LAAPClient({ baseUrl: 'http://127.0.0.1:11521', token: '<TOKEN>' });
 *   await c.signCharter('my-spirit');
 *   const presets = await c.listPresets();
 *   const r = await c.callMCP('memory_retrieve', { query: 'hello', top_k: 3 });
 */
(function(w){'use strict';

const DEFAULTS = {
  baseUrl: 'http://127.0.0.1:11521',
  token: '',
  timeout: 10000,
  debug: false
};

class LAAPClient {
  constructor(opts) {
    this.c = Object.assign({}, DEFAULTS, opts || {});
    if (!this.c.baseUrl) throw new Error('LAAPClient: baseUrl required');
    this.baseUrl = this.c.baseUrl.replace(/\/+$/, '');
  }

  // ── 内部 fetch 封装 ─────────────────────────────────────────
  async _req(method, path, body) {
    const url = this.baseUrl + path;
    const headers = { 'Accept': 'application/json' };
    if (this.c.token) headers['Authorization'] = 'Bearer ' + this.c.token;
    if (body !== undefined && body !== null) {
      headers['Content-Type'] = 'application/json';
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.c.timeout);
    let resp;
    try {
      resp = await fetch(url, {
        method: method,
        headers: headers,
        body: body !== undefined && body !== null ? JSON.stringify(body) : undefined,
        signal: ctrl.signal
      });
    } catch (e) {
      clearTimeout(timer);
      throw new Error('LAAPClient ' + method + ' ' + path + ' unreachable: ' + (e && e.message ? e.message : e));
    }
    clearTimeout(timer);
    const text = await resp.text();
    let data = null;
    if (text) {
      try { data = JSON.parse(text); }
      catch (e) { data = { raw: text }; }
    }
    if (!resp.ok) {
      const msg = (data && (data.error || data.message)) || ('HTTP ' + resp.status);
      throw new Error('LAAPClient ' + method + ' ' + path + ' -> ' + resp.status + ': ' + msg);
    }
    return data === null ? {} : data;
  }

  // ── 健康检查 ────────────────────────────────────────────────
  health() { return this._req('GET', '/health'); }

  // ── 宪章 ────────────────────────────────────────────────────
  /**
   * 拉取宪章文本。返回 { text, hash }。
   */
  getCharter() { return this._req('GET', '/charter/text'); }

  /**
   * 完整宪章签署流程：拉取宪章文本 → 用生命体名生成签名占位 → 写入见证迹。
   * 注意：浏览器端不持有 Ed25519 私钥，签名占位为空字符串；真正的私钥
   * 签名应在 sidecar 进程内完成。此处仅完成"拉文本 + 写见证"两步。
   * @param {string} lifeformName 生命体名
   * @returns {Promise<{charter_hash, charter_signature, witness_id, recorded_at}>}
   */
  async signCharter(lifeformName) {
    const charter = await this.getCharter();
    const charterText = charter.text || charter.charter_text || '';
    const charterHash = charter.hash || charter.charter_hash || '';
    const signature = '';  // 浏览器无私钥，签名由 sidecar 内部完成
    const witness = await this._req('POST', '/witness/record', {
      event_type: 'charter_signed',
      target_module: 'web_sdk_js',
      payload: {
        lifeform_name: lifeformName || 'anonymous',
        charter_hash: charterHash,
        charter_text: charterText
      },
      signature: signature
    });
    return {
      charter_hash: charterHash,
      charter_signature: signature,
      witness_id: witness.witness_id || '',
      recorded_at: witness.recorded_at || Math.floor(Date.now() / 1000)
    };
  }

  // ── 预设市场 ────────────────────────────────────────────────
  /**
   * 列出 LAAPer 市场中的预设生命体。返回 { items: [...] }。
   */
  listPresets() { return this._req('GET', '/preset/list'); }

  /**
   * 获取预设详情。preset_id 可以是字符串或 { preset_id }。
   */
  getPreset(presetId) {
    const body = typeof presetId === 'object' ? presetId : { preset_id: presetId };
    return this._req('POST', '/preset/get', body);
  }

  /**
   * 克隆一个预设生命体到本地。
   * @param {string} presetId 预设 ID
   * @param {string} newName 克隆后的生命体名
   */
  clonePreset(presetId, newName) {
    return this._req('POST', '/preset/clone', {
      preset_id: presetId,
      new_name: newName
    });
  }

  // ── 通用 MCP 调用 ───────────────────────────────────────────
  /**
   * 通过 sidecar 的 /mcp/call 调用任意 MCP 工具。
   * @param {string} tool 工具名，如 'memory_retrieve'
   * @param {object} args 工具入参
   */
  async callMCP(tool, args) {
    const resp = await this._req('POST', '/mcp/call', { tool: tool, args: args || {} });
    return resp && resp.result !== undefined ? resp.result : resp;
  }

  // ── 见证迹 ──────────────────────────────────────────────────
  witnessQuery(targetModule, since) {
    return this._req('POST', '/witness/query', {
      target_module: targetModule, since: since || 0
    });
  }
  witnessVerify(witnessId) {
    return this._req('POST', '/witness/verify', { witness_id: witnessId });
  }
  witnessStats() { return this._req('GET', '/witness/stats'); }
}

// 暴露到全局
w.LAAPClient = LAAPClient;
// 便捷工厂
w.LAAP = w.LAAP || {};
w.LAAP.client = (opts) => new LAAPClient(opts);

})(typeof window !== 'undefined' ? window : this);
