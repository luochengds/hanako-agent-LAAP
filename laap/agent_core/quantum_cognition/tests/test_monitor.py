"""Quick test for CognitionMonitor."""
import sys, os, json, tempfile, shutil
sys.path.insert(0, 'D:/LAAP')
from laap.agent_core.quantum_cognition.cognition_monitor import CognitionMonitor

tmp = tempfile.mkdtemp()
mon = CognitionMonitor(log_dir=tmp)

for i in range(5):
    mon.log_turn(
        quantum_stats={'confidence': 0.5+i*0.1, 'uncertainty': 0.5-i*0.05, 'quantum_entropy': 0.1, 'spectral_coherence': 0.6, 'arousal': 0.3, 'curiosity': 1.0},
        guard_decision={'action': 'generate', 'reason': 'pass'},
        validation_result={'is_valid': True, 'needs_caveat': False, 'issues': []},
        generation_params={'temperature': 0.7, 'top_p': 0.9, 'hqkv_prefix_tokens': 38},
        timing={'cognition_ms': 0.7, 'generation_ms': 850.0, 'total_ms': 860.0},
        tokens={'input_tokens': 150, 'output_tokens': 85},
        success=True,
    )

log_path = os.path.join(tmp, os.listdir(tmp)[0])
with open(log_path) as f:
    records = [json.loads(line) for line in f]

print(f'Records written: {len(records)}')
print(f'First record keys: {list(records[0].keys())}')
print(f'Confidence: {records[0]["confidence"]}')
print(f'Guard action: {records[0]["guard_action"]}')
print(f'Token overhead: {records[0].get("hqkv_prefix_tokens", 0)}')
print(f'Monitor stats: {mon.get_stats()}')

mon.close()
shutil.rmtree(tmp)
print('Monitor test: PASSED')
