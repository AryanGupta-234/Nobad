/// The engine's model catalogue (contract additions for 0.8: `models`, `model_use`, `model_download`,
/// `model_remove`, `auto_configure`, and the `models` event): this PC, the recommended tier, and every model with
/// what it does, what it costs, and whether this PC can run it.
library;

import 'json.dart';
import 'settings.dart' show Hardware;

enum ModelUseState { notDownloaded, downloading, ready, active, failed }

const _states = {
  'not_downloaded': ModelUseState.notDownloaded,
  'downloading': ModelUseState.downloading,
  'ready': ModelUseState.ready,
  'active': ModelUseState.active,
  'failed': ModelUseState.failed,
};

String featureLabel(String feature) =>
    const {'text': 'Meaning search', 'photo': 'Photos by what is in them', 'ocr': 'Words in pictures'}[feature] ??
    feature;

String tierLabel(String tier) =>
    const {'light': 'Light', 'balanced': 'Balanced', 'best': 'Best', 'custom': 'Custom'}[tier] ?? tier;

class ModelInfo {
  const ModelInfo({
    required this.id,
    this.feature = 'text',
    this.name = '',
    this.tier = '',
    this.licence = '',
    this.source = '',
    this.sizeMb = 0,
    this.ramMb = 0,
    this.speedNote = '',
    this.languages = const [],
    this.improves = '',
    this.builtin = false,
    this.state = ModelUseState.notDownloaded,
    this.capable = true,
    this.capableReason = '',
    this.recommended = false,
  });
  final String id;
  final String feature;
  final String name;
  final String tier;
  final String licence;
  final String source;
  final double sizeMb;
  final double ramMb;
  final String speedNote;
  final List<String> languages;
  final String improves;
  final bool builtin;
  final ModelUseState state;
  final bool capable;
  final String capableReason;
  final bool recommended;

  bool get onDisk => builtin || state == ModelUseState.ready || state == ModelUseState.active;

  static ModelInfo? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['id']).isEmpty) return null;
    return ModelInfo(
      id: jStr(m['id']),
      feature: jStr(m['feature']),
      name: jStr(m['name']),
      tier: jStr(m['tier']),
      licence: jStr(m['licence']),
      source: jStr(m['source']),
      sizeMb: jNum(m['size_mb']),
      ramMb: jNum(m['ram_mb']),
      speedNote: jStr(m['speed_note']),
      languages: jStrs(m['languages']),
      improves: jStr(m['improves']),
      builtin: jBool(m['builtin']),
      state: _states[m['state']] ?? ModelUseState.notDownloaded,
      capable: m['capable'] != false,
      capableReason: jStr(m['capable_reason']),
      recommended: jBool(m['recommended']),
    );
  }
}

class ModelsInfo {
  const ModelsInfo({this.pc, this.tierRecommended = '', this.tierCurrent = '', this.models = const []});
  final Hardware? pc;
  final String tierRecommended;
  final String tierCurrent;
  final List<ModelInfo> models;

  List<ModelInfo> byFeature(String feature) => [
    for (final m in models)
      if (m.feature == feature) m,
  ];

  static ModelsInfo fromJson(Object? v) {
    final m = jMap(v);
    return ModelsInfo(
      pc: Hardware.fromJson(m['pc']),
      tierRecommended: jStr(m['tier_recommended']),
      tierCurrent: jStr(m['tier_current']),
      models: jList(m['models'], ModelInfo.fromJson),
    );
  }
}

/// `model_use` answer.
class ModelUse {
  const ModelUse(this.ok, {this.error = '', this.needsDownload = false});
  final bool ok;
  final String error;
  final bool needsDownload;

  static ModelUse fromJson(Object? v) {
    final m = jMap(v);
    return ModelUse(jBool(m['ok']), error: jStr(m['error']), needsDownload: jBool(m['needs_download']));
  }
}

class AutoStep {
  const AutoStep({required this.feature, required this.id, this.needsDownload = false});
  final String feature;
  final String id;
  final bool needsDownload;
}

/// `auto_configure` answer: the tier it chose and what it changes (downloads still need consent).
class AutoConfig {
  const AutoConfig({this.tier = '', this.steps = const []});
  final String tier;
  final List<AutoStep> steps;

  static AutoConfig fromJson(Object? v) {
    final m = jMap(v);
    return AutoConfig(
      tier: jStr(m['tier']),
      steps: jList(m['steps'], (s) {
        final x = jMap(s);
        if (jStr(x['id']).isEmpty) return null;
        return AutoStep(feature: jStr(x['feature']), id: jStr(x['id']), needsDownload: jBool(x['needs_download']));
      }),
    );
  }
}
