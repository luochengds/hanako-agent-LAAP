"""LAAP SaaS v2.0 — 端到端集成测试"""
import sys, json, time, os, subprocess, urllib.request, signal

# 启动服务器
proc = subprocess.Popen(
    [sys.executable, "-c", """
import logging; logging.basicConfig(level=logging.WARNING)
from laap.saas.server.app import create_app
import uvicorn
uvicorn.run(create_app(':memory:'), host='127.0.0.1', port=18914, log_level='warning')
"""],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
)
time.sleep(4)

base = 'http://127.0.0.1:18914'
tests = 0
passed = 0

def get(url):
    r = urllib.request.urlopen(url, timeout=5)
    return json.loads(r.read().decode())

def post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())

def patch(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method='PATCH')
    return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())

def delete(url):
    req = urllib.request.Request(url, method='DELETE')
    return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())

def check(name, condition):
    global tests, passed
    tests += 1
    ok = condition()
    if ok:
        passed += 1
        print(f'  ✅ {name}')
    else:
        print(f'  ❌ {name}')

try:
    # Test 1: Health
    h = get(f'{base}/health')
    check('Health endpoint', lambda: h['status'] == 'ok' and h['version'] == '2.0.0')

    # Test 2: Register schema
    r = post(f'{base}/api/schema/register', {
        'name': 'product',
        'schema': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'price': {'type': 'number'},
                'active': {'type': 'boolean', 'default': True},
            },
            'required': ['name', 'price'],
            'x-tenant-isolated': True,
        }
    })
    check('Register schema', lambda: r['status'] == 'registered' and r['fields'] == 3)

    # Test 3: Create
    p = post(f'{base}/api/v1/product', {'name': '叉车', 'price': 2999, 'active': True})
    check('Create product', lambda: p['name'] == '叉车' and p['price'] == 2999)

    # Test 4: Read
    r2 = get(f'{base}/api/v1/product/{p["id"]}')
    check('Read product', lambda: r2['name'] == '叉车' and r2['price'] == 2999)

    # Test 5: Update
    r3 = patch(f'{base}/api/v1/product/{p["id"]}', {'price': 1999})
    check('Update product', lambda: r3['price'] == 1999)

    # Test 6: Query
    req = urllib.request.Request(f'{base}/api/v1/product')
    q = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
    check('Query products', lambda: q['total'] == 1 and len(q['data']) == 1)

    # Test 7: Delete
    d = delete(f'{base}/api/v1/product/{p["id"]}')
    check('Delete product', lambda: d['status'] == 'deleted')

    # Test 8: Schema list
    s = get(f'{base}/api/schema')
    check('Schema list', lambda: len(s['models']) == 1 and s['models'][0]['name'] == 'product')

    # Test 9: Tenant
    t = post(f'{base}/api/tenants', {'id': 'acme', 'name': 'Acme Corp'})
    check('Create tenant', lambda: t['id'] == 'acme')

    # Test 10: Multi-tenant isolation
    p1 = post(f'{base}/api/v1/product', {'name': '公共产品', 'price': 100})
    req2 = urllib.request.Request(f'{base}/api/v1/product',
        headers={'X-Tenant-Id': 'acme'})
    q2 = json.loads(urllib.request.urlopen(req2, timeout=5).read().decode())
    check('Tenant isolation (acme empty)', lambda: q2['total'] == 0)

    # Test 11: Create in tenant
    p2 = post(f'{base}/api/v1/product', {'name': 'Acme产品', 'price': 999})
    req3 = urllib.request.Request(f'{base}/api/v1/product',
        headers={'X-Tenant-Id': 'acme'})
    q3 = json.loads(urllib.request.urlopen(req3, timeout=5).read().decode())
    check('Tenant isolation (acme has 1)', lambda: q3['total'] == 1)

    # Test 12: Health with models
    h2 = get(f'{base}/health')
    check('Health shows models', lambda: len(h2['models']) == 1)

    print(f'\n结果: {passed}/{tests} 通过')
finally:
    proc.kill()
    proc.wait()

sys.exit(0 if passed == tests else 1)
