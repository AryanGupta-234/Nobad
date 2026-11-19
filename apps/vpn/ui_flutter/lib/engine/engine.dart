/// What the screens can ask the engine, typed after apps/vpn/contract (protocol 1).
///
/// - [PipeEngine]: the app's engine, over the pipe only. Offline: [EngineOffline]. Never a made-up answer.
/// - FakeEngine (fake_engine.dart): in memory, for tests, goldens and the explicit NOBAD_VPN_FAKE_ENGINE=1 demo.
///
/// Every request names a server by its config name and a link by its key: never a path, a URL to fetch as admin,
/// or a command. The engine checks each parameter again (nobadvpn/rpc/params.py).
library;

import 'package:flutter/foundation.dart';

import 'models.dart';
import 'rpc.dart';

export 'rpc.dart' show EngineEvent, EngineOffline, Link, RpcException;

abstract class EngineApi {
  ValueListenable<Link> get link;
  Stream<EngineEvent> get events;

  /// Any contract method by name.
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]);

  /// The window is on screen (true) or hidden/minimized (false).
  Future<void> shown(bool on);
  String get engineVersion;
  void dispose();
}

class PipeEngine implements EngineApi {
  PipeEngine(this._pipe);
  final EngineClient _pipe;

  @override
  ValueListenable<Link> get link => _pipe.link;
  @override
  Stream<EngineEvent> get events => _pipe.events;
  @override
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) => _pipe.call(method, params);
  @override
  Future<void> shown(bool on) => _pipe.shown(on);
  @override
  String get engineVersion => _pipe.engineVersion;
  @override
  void dispose() => _pipe.dispose();
}

/// The typed calls. Each one's method and params are exactly a line of contract/transcripts (test/contract).
extension VpnCalls on EngineApi {
  Future<Answer> _ok(String m, [Map<String, Object?> p = const {}]) async => Answer.fromJson(await call(m, p));

  Future<VpnState> state() async => VpnState.fromJson(await call('state'));

  // connection
  Future<Answer> connect(String name) => _ok('connect', {'name': name});
  Future<Answer> disconnect() => _ok('disconnect');
  Future<Answer> fastest() => _ok('fastest');
  Future<Answer> smart() => _ok('smart');
  Future<Answer> probe() => _ok('probe');
  Future<Answer> favorite(String name) => _ok('favorite', {'name': name});
  Future<Answer> endpointCheck(String name) => _ok('endpoint_check', {'name': name});
  Future<Answer> dismissError() => _ok('dismiss_error');
  Future<Answer> panic() => _ok('panic_reset');
  Future<Answer> netRepair(String level) => _ok('net_repair', {'level': level});

  // settings
  Future<Answer> setSetting(String key, Object value) => _ok('settings', {'key': key, 'value': value});
  Future<Answer> theme(bool dark) => _ok('theme', {'value': dark ? 'dark' : 'light'});
  Future<Answer> wizardDone() => _ok('wizard_done');
  Future<Answer> trustedAdd([String? name]) => _ok('trusted_add', {'name': ?name});

  // servers and configs
  Future<Answer> rescan() => _ok('rescan');
  Future<Answer> openConfigs() => _ok('open_configs');
  Future<Answer> importConfig(String name, String content) => _ok('import', {'name': name, 'content': content});
  Future<Answer> importUrl(String url) => _ok('import_url', {'url': url});
  Future<Answer> freeScan() => _ok('free_scan');
  Future<Answer> freeImport(List<String> files) => _ok('free_import', {'files': files});
  Future<Answer> configGet(String name) => _ok('config_get', {'name': name});
  Future<Answer> configValidate(String name, String text) => _ok('config_validate', {'name': name, 'text': text});
  Future<Answer> configSave(String name, String text) => _ok('config_save', {'name': name, 'text': text});
  Future<Answer> configDelete(String name) => _ok('config_delete', {'name': name});

  // setup, links, help
  Future<Answer> installWireguard() => _ok('install_wireguard');
  Future<Answer> elevate() => _ok('elevate');
  Future<Answer> openUrl(String key) => _ok('open_url', {'key': key});
  Future<Answer> diagnosticsExport() => _ok('diagnostics_export');
  Future<Answer> reportProblem({bool crash = false}) => _ok('report_problem', {if (crash) 'crash': true});
  Future<Answer> updateCheck() => _ok('update_check');
  Future<Answer> updateInstall() => _ok('update_install');
  Future<Answer> reachTest() => _ok('reach_test');
  Future<Answer> reachForget() => _ok('reach_forget');
  Future<Answer> ipinfo() => _ok('ipinfo');
  Future<Answer> quit({bool disconnect = false}) => _ok('quit', {if (disconnect) 'disconnect': true});

  /// Ask for a window ("main" / "mini"); `shown` false + `launched` false: start it yourself.
  Future<Answer> uiShow(String window) => _ok('ui_show', {'window': window});
}
