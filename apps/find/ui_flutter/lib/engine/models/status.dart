/// The engine's status: the short part every status line needs (Api.status_brief, served by the prototype
/// engine) and the details the Indexing page shows (Api.status in 0.7.0: phases, resources, models, activity).
///
/// The `status` event carries the short part today; the details arrive in the same event once the engine's
/// contract has them (FakeEngine sends them now). Everything here is parsed leniently.
library;

import 'format.dart';
import 'json.dart';

class EngineStatus {
  const EngineStatus({
    this.level = '',
    this.reason = '',
    this.phase = '',
    this.files = 0,
    this.paused = '',
    this.details,
  });

  final String level;
  final String reason;
  final String phase;
  final int files;
  final String paused;

  /// Null when the engine only sent the short status.
  final IndexDetails? details;

  static EngineStatus fromJson(Object? json) {
    final m = jMap(json);
    final f = jInt(m['files']);
    return EngineStatus(
      level: jStr(m['level']),
      reason: jStr(m['reason']),
      phase: jStr(m['phase']),
      paused: jStr(m['paused']),
      files: f < 0 ? 0 : f,
      details: m.containsKey('phases') || m.containsKey('resources') ? IndexDetails.fromJson(m) : null,
    );
  }

  /// The short fields from [brief] on top of these details (a real engine's brief status + fake details).
  EngineStatus withBrief(EngineStatus brief) => EngineStatus(
    level: brief.level,
    reason: brief.reason,
    phase: brief.phase,
    files: brief.files,
    paused: brief.paused,
    details: details,
  );

  static const phaseLabels = {
    'starting': 'Starting',
    'names': 'Finding files',
    'text': 'Reading text',
    'images': 'Reading photos and scans',
    'photos': 'Understanding photos',
    'meaning': 'Learning meaning',
    'watching': 'Up to date',
    'error': 'Stopped',
  };
  static const levelLabels = {
    'full': 'Working at full speed',
    'gentle': 'Working gently',
    'light': 'Working very lightly',
    'paused': 'Paused',
  };

  String get phaseLabel => paused.isNotEmpty ? 'Paused · $paused' : (phaseLabels[phase] ?? phase);
  String get levelLabel => levelLabels[level] ?? '';

  /// One of full/gentle/light/paused (an unknown level is shown as light, like 0.7.0).
  String get levelKey => levelLabels.containsKey(level) ? level : 'light';
  bool get isPaused => level == 'paused';

  @override
  bool operator ==(Object other) =>
      other is EngineStatus &&
      other.level == level &&
      other.reason == reason &&
      other.phase == phase &&
      other.files == files &&
      other.paused == paused &&
      identical(other.details, details);

  @override
  int get hashCode => Object.hash(level, reason, phase, files, paused, details);
}

class IndexDetails {
  const IndexDetails({
    this.version = '',
    this.withText = 0,
    this.vectors = 0,
    this.nameVectors = 0,
    this.photoVectors = 0,
    this.memoryMb,
    this.modelsLoaded = const [],
    this.rate = 0,
    this.dbBytes = 0,
    this.plan,
    this.speed = '',
    this.ocrOn = false,
    this.ocrWhy = '',
    this.roots = const [],
    this.drives = const [],
    this.encrypted = false,
    this.model = const ModelState(),
    this.photoModel = const ModelState(),
    this.history = const [],
    this.resources = const Resources(),
    this.phases = const [],
    this.models = const [],
    this.activity = const [],
  });

  final String version;
  final int withText;
  final int vectors;
  final int nameVectors;
  final int photoVectors;
  final double? memoryMb;
  final List<String> modelsLoaded;
  final double rate;
  final int dbBytes;
  final WorkPlan? plan;
  final String speed;
  final bool ocrOn;
  final String ocrWhy;
  final List<String> roots;
  final List<Drive> drives;
  final bool encrypted;
  final ModelState model;
  final ModelState photoModel;
  final List<HistoryPoint> history;
  final Resources resources;
  final List<PhaseRow> phases;
  final List<ModelCard> models;
  final List<ActivityEntry> activity;

  static IndexDetails fromJson(Map<String, Object?> m) {
    final ocr = m['ocr'];
    final plan = m['plan'];
    return IndexDetails(
      version: jStr(m['version']),
      withText: jInt(m['with_text']),
      vectors: jInt(m['vectors']),
      nameVectors: jInt(m['name_vectors']),
      photoVectors: jInt(m['photo_vectors']),
      memoryMb: jNumOrNull(m['memory_mb']),
      modelsLoaded: jStrs(m['models_loaded']),
      rate: jNum(m['rate']),
      dbBytes: jInt(m['db_bytes']),
      plan: plan is Map && plan.isNotEmpty ? WorkPlan.fromJson(jMap(plan)) : null,
      speed: jStr(m['speed']),
      ocrOn: ocr == true,
      ocrWhy: ocr is String ? ocr : '',
      roots: jStrs(m['roots']),
      drives: jList(m['drives'], Drive.fromJson),
      encrypted: jBool(m['encrypted']),
      model: ModelState.fromJson(m['model']),
      photoModel: ModelState.fromJson(m['photo_model']),
      history: jList(m['history'], HistoryPoint.fromJson),
      resources: Resources.fromJson(m['resources']),
      phases: jList(m['phases'], PhaseRow.fromJson),
      models: jList(m['models'], ModelCard.fromJson),
      activity: jList(m['activity'], ActivityEntry.fromJson),
    );
  }

  /// "gentle" from "gentle (you're using the PC)".
  String get speedLabel => speed.split(' (').first;

  /// "Speed: you're using the PC", or "Speed".
  String get speedHelp {
    final i = speed.indexOf(' (');
    if (i < 0) return 'Speed';
    return 'Speed: ${speed.substring(i + 2).replaceAll(')', '')}';
  }
}

class WorkPlan {
  const WorkPlan({this.cpu = 0, this.textWorkers = 0, this.textWorkersIdle = 0, this.ssd});
  final int cpu;
  final int textWorkers;
  final int textWorkersIdle;
  final bool? ssd;

  static WorkPlan fromJson(Map<String, Object?> m) => WorkPlan(
    cpu: jInt(m['cpu']),
    textWorkers: jInt(m['text_workers']),
    textWorkersIdle: jInt(m['text_workers_idle']),
    ssd: m['ssd'] is bool ? m['ssd'] as bool : null,
  );
}

class Drive {
  const Drive({required this.root, this.label = '', this.type = 'fixed', this.present = true});
  final String root;
  final String label;
  final String type;
  final bool present;

  static const typeLabels = {
    'fixed': 'this PC',
    'removable': 'USB / external',
    'network': 'network',
    'cd': 'disc',
    'ram': 'RAM disk',
  };
  String get typeLabel => typeLabels[type] ?? type;

  static Drive? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['root']).isEmpty) return null;
    return Drive(root: jStr(m['root']), label: jStr(m['label']), type: jStr(m['type']), present: m['present'] != false);
  }
}

/// A model download's state (Api._model): missing | downloading | ready.
class ModelState {
  const ModelState({this.state = 'missing', this.got = 0, this.size = 0, this.error = '', this.mbS = 0});
  final String state;

  /// Bytes so far and in all.
  final int got;
  final int size;
  final String error;

  /// Download speed (download events only).
  final double mbS;

  bool get ready => state == 'ready';
  bool get downloading => state == 'downloading';
  int get percent => size > 0 ? (100 * got / size).round().clamp(0, 100) : 0;

  static ModelState fromJson(Object? v) {
    final m = jMap(v);
    return ModelState(
      state: jStr(m['state']).isEmpty ? 'missing' : jStr(m['state']),
      got: jInt(m['got']),
      size: jInt(m['size']),
      error: jStr(m['error']),
    );
  }
}

/// One governor sample (every 2 s, 150 kept: five minutes).
class HistoryPoint {
  const HistoryPoint({this.t = 0, this.findCpu = 0, this.findMb = 0});
  final double t;
  final double findCpu;
  final double findMb;

  static HistoryPoint? fromJson(Object? v) {
    if (v is! Map) return null;
    final m = jMap(v);
    return HistoryPoint(
      t: jNum(m['t']),
      findCpu: jNum(m['find_cpu']).clamp(0, 100).toDouble(),
      findMb: jNum(m['find_mb']).clamp(0, double.maxFinite).toDouble(),
    );
  }
}

class ProcessUse {
  const ProcessUse({required this.name, this.pid = 0, this.cpu = 0, this.memoryMb = 0});
  final String name;
  final int pid;
  final double cpu;
  final double memoryMb;

  static ProcessUse? fromJson(Object? v) {
    final m = jMap(v);
    if (m.isEmpty) return null;
    return ProcessUse(name: jStr(m['name']), pid: jInt(m['pid']), cpu: jNum(m['cpu']), memoryMb: jNum(m['memory_mb']));
  }
}

class Resources {
  const Resources({this.cpu, this.memoryMb, this.readMbS, this.gpu, this.processes = const []});
  final double? cpu;
  final double? memoryMb;
  final double? readMbS;

  /// Null: the graphics card isn't used.
  final double? gpu;
  final List<ProcessUse> processes;

  static Resources fromJson(Object? v) {
    final m = jMap(v);
    return Resources(
      cpu: jNumOrNull(m['cpu']),
      memoryMb: jNumOrNull(m['memory_mb']),
      readMbS: jNumOrNull(m['read_mb_s']),
      gpu: jNumOrNull(m['gpu']),
      processes: jList(m['processes'], ProcessUse.fromJson),
    );
  }
}

enum PhaseState { waiting, running, done, off }

class PhaseRow {
  const PhaseRow({
    required this.id,
    required this.label,
    this.state = PhaseState.waiting,
    this.done = 0,
    this.total,
    this.rate = 0,
    this.etaS,
  });
  final String id;
  final String label;
  final PhaseState state;
  final int done;
  final int? total;
  final double rate;
  final int? etaS;

  static const stateLabels = {
    PhaseState.waiting: 'Waiting',
    PhaseState.running: 'Working',
    PhaseState.done: 'Done',
    PhaseState.off: 'Off',
  };
  String get stateLabel => stateLabels[state]!;

  bool get known => (total ?? 0) > 0;
  double get fraction => state == PhaseState.done
      ? 1
      : known
      ? (done / total!).clamp(0, 1).toDouble()
      : 0;

  /// Running but with no total: an indeterminate meter.
  bool get busy => state == PhaseState.running && !known;

  String get count {
    if (state == PhaseState.off) return '';
    if (known) return '${groupDigits(done)} / ${groupDigits(total!)}';
    return done > 0 ? groupDigits(done) : '';
  }

  String get extra {
    if (state != PhaseState.running) return '';
    return [perTime(rate, 'files'), if (etaS != null) 'done in ${span(etaS!)}'].where((s) => s.isNotEmpty).join(' · ');
  }

  static PhaseRow? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['id']).isEmpty) return null;
    return PhaseRow(
      id: jStr(m['id']),
      label: jStr(m['label']),
      state: PhaseState.values.firstWhere((s) => s.name == m['state'], orElse: () => PhaseState.waiting),
      done: jInt(m['done']),
      total: jIntOrNull(m['total']),
      rate: jNum(m['rate']),
      etaS: jIntOrNull(m['eta_s']),
    );
  }
}

class DownloadProgress {
  const DownloadProgress({this.gotMb = 0, this.sizeMb = 0, this.mbS = 0});
  final double gotMb;
  final double sizeMb;
  final double mbS;
  double get fraction => sizeMb > 0 ? (gotMb / sizeMb).clamp(0, 1).toDouble() : 0;

  static DownloadProgress? fromJson(Object? v) {
    if (v is! Map) return null;
    final m = jMap(v);
    return DownloadProgress(gotMb: jNum(m['got_mb']), sizeMb: jNum(m['size_mb']), mbS: jNum(m['mb_s']));
  }
}

class ModelCard {
  const ModelCard({
    required this.id,
    required this.name,
    this.license = '',
    this.sizeMb = 0,
    this.onDisk = false,
    this.loaded = false,
    this.memoryMb,
    this.device = '',
    this.items = 0,
    this.download,
  });
  final String id;
  final String name;
  final String license;
  final double sizeMb;
  final bool onDisk;
  final bool loaded;
  final double? memoryMb;
  final String device;
  final int items;
  final DownloadProgress? download;

  String get stateLine {
    final dl = download;
    if (dl != null) {
      return 'Downloading ${mb(dl.gotMb)} of ${mb(dl.sizeMb)}${dl.mbS > 0 ? ' at ${dl.mbS.toStringAsFixed(1)} MB/s' : ''}';
    }
    if (loaded) return 'In use now${device.isNotEmpty ? ' on $device' : ''}';
    return onDisk ? 'Ready, loads when needed' : 'Not downloaded';
  }

  String get facts => [
    sizeMb > 0 ? '${mb(sizeMb)} download' : 'Built into Windows',
    license,
    if (loaded && memoryMb != null && memoryMb! > 0) '${mb(memoryMb)} of memory',
    if (items > 0) '${groupDigits(items)} items made',
  ].where((s) => s.isNotEmpty).join(' · ');

  static ModelCard? fromJson(Object? v) {
    final m = jMap(v);
    if (m.isEmpty) return null;
    return ModelCard(
      id: jStr(m['id']),
      name: jStr(m['name']),
      license: jStr(m['license']),
      sizeMb: jNum(m['size_mb']),
      onDisk: jBool(m['on_disk']),
      loaded: jBool(m['loaded']),
      memoryMb: jNumOrNull(m['memory_mb']),
      device: jStr(m['device']),
      items: jInt(m['items']),
      download: DownloadProgress.fromJson(m['download']),
    );
  }
}

class ActivityEntry {
  const ActivityEntry({required this.t, this.kind = 'info', required this.text});
  final double t;
  final String kind;
  final String text;

  static ActivityEntry? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['text']).isEmpty) return null;
    return ActivityEntry(t: jNum(m['t']), kind: jStr(m['kind']), text: jStr(m['text']));
  }
}
