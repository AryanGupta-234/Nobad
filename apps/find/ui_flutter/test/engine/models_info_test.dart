import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/models_info.dart';

const sample = {
  'pc': {
    'ram_gb': 15.7,
    'cores': 8,
    'threads': 16,
    'avx2': true,
    'avx512_vnni': false,
    'gpu': 'Intel Iris Xe',
    'vram_gb': 0.1,
    'directml': false,
    'disk_free_gb': 120.5,
    'ssd': true,
  },
  'tier_recommended': 'balanced',
  'tier_current': 'custom',
  'models': [
    {
      'id': 'minilm',
      'feature': 'text',
      'name': 'all-MiniLM-L6-v2',
      'tier': 'light',
      'licence': 'Apache-2.0',
      'source': 'Hugging Face',
      'size_mb': 23,
      'ram_mb': 90,
      'speed_note': 'Fast on any PC',
      'languages': ['English'],
      'improves': 'Search by meaning',
      'builtin': false,
      'state': 'active',
      'capable': true,
      'capable_reason': '',
      'recommended': false,
    },
    {
      'id': 'e5-base',
      'feature': 'text',
      'name': 'multilingual-e5-base',
      'tier': 'best',
      'licence': 'MIT',
      'source': 'Hugging Face',
      'size_mb': 280,
      'ram_mb': 700,
      'speed_note': 'Slower',
      'languages': ['100+'],
      'improves': 'Meaning in many languages',
      'builtin': false,
      'state': 'not_downloaded',
      'capable': false,
      'capable_reason': 'Needs 16 GB of memory',
      'recommended': false,
    },
    {
      'id': 'winocr',
      'feature': 'ocr',
      'name': 'Windows OCR',
      'tier': 'light',
      'licence': 'Windows',
      'source': 'Windows',
      'size_mb': 0,
      'ram_mb': 0,
      'speed_note': '',
      'languages': [],
      'improves': 'Words in pictures',
      'builtin': true,
      'state': 'ready',
      'capable': true,
      'capable_reason': '',
      'recommended': true,
    },
    'junk',
  ],
};

void main() {
  test('the models answer: the PC, the tiers, every model with its facts', () {
    final m = ModelsInfo.fromJson(sample);
    expect(m.pc!.threads, 16);
    expect(m.tierRecommended, 'balanced');
    expect(m.tierCurrent, 'custom');
    expect(m.models, hasLength(3));
    final e5 = m.models[1];
    expect(e5.capable, isFalse);
    expect(e5.capableReason, 'Needs 16 GB of memory');
    expect(e5.state, ModelUseState.notDownloaded);
    expect(m.models.first.state, ModelUseState.active);
    expect(m.models.last.builtin, isTrue);
    expect(m.byFeature('text').map((x) => x.id), ['minilm', 'e5-base']);
    expect(featureLabel('ocr'), 'Words in pictures');
    expect(tierLabel('balanced'), 'Balanced');
  });

  test('odd answers become safe defaults', () {
    final m = ModelsInfo.fromJson('nope');
    expect(m.models, isEmpty);
    expect(m.pc, isNull);
    expect(ModelInfo.fromJson({'id': 'x', 'state': 'weird'})!.state, ModelUseState.notDownloaded);
    expect(ModelUse.fromJson({'ok': false, 'error': 'e', 'needs_download': true}).needsDownload, isTrue);
    final a = AutoConfig.fromJson({
      'tier': 'light',
      'steps': [
        {'feature': 'text', 'id': 'minilm', 'needs_download': true},
      ],
    });
    expect(a.steps.single.needsDownload, isTrue);
  });

  test('the models event and the show event for the tray pages', () {
    expect((EngineEvent.parse('models', sample) as ModelsEvent).info.models, hasLength(3));
    expect((EngineEvent.parse('show', {'what': 'settings', 'text': null}) as ShowEvent).what, 'settings');
    expect((EngineEvent.parse('show', {'what': 'index', 'text': null}) as ShowEvent).what, 'index');
    expect((EngineEvent.parse('show', {'what': 'nonsense'}) as ShowEvent).what, 'main');
  });
}
