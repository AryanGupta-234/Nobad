#include <flutter/dart_project.h>
#include <flutter/flutter_view_controller.h>
#include <flutter_windows.h>
#include <windows.h>

#include <algorithm>
#include <cwchar>

#include "flutter_window.h"
#include "utils.h"

// The quick find bar: 640 x 64 (logical) on the monitor with the mouse, centered,
// a third of the way down its work area (the same rule as nobadfind/bar.py).
static void PlaceBar(HWND hwnd) {
  POINT pt{};
  GetCursorPos(&pt);
  HMONITOR monitor = MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST);
  MONITORINFO info{};
  info.cbSize = sizeof(info);
  if (!GetMonitorInfo(monitor, &info)) {
    return;
  }
  const double scale = FlutterDesktopGetDpiForMonitor(monitor) / 96.0;
  const RECT& r = info.rcWork;
  const int w = static_cast<int>(640 * scale + 0.5);
  const int h = static_cast<int>(64 * scale + 0.5);
  const int x = r.left + (r.right - r.left - w) / 2;
  const int y = r.top + (r.bottom - r.top) / 3 - h / 2;
  SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE);
}

int APIENTRY wWinMain(_In_ HINSTANCE instance, _In_opt_ HINSTANCE prev,
                      _In_ wchar_t *command_line, _In_ int show_command) {
  // Attach to console when present (e.g., 'flutter run') or create a
  // new console when running with a debugger.
  if (!::AttachConsole(ATTACH_PARENT_PROCESS) && ::IsDebuggerPresent()) {
    CreateAndAttachConsole();
  }

  // Initialize COM, so that it is available for use in the library and/or
  // plugins.
  ::CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

  flutter::DartProject project(L"data");
  project.set_gpu_preference(flutter::GpuPreference::LowPowerPreference);

  // Skia, not Impeller: on the reference PC (Intel Iris Xe) Skia starts in ~0.2 s instead of ~0.9 s and uses
  // ~50 MB less (docs/measurements.md). NOBAD_FIND_RENDERER=impeller switches back, for measuring.
  wchar_t renderer[16] = {};
  const bool impeller =
      GetEnvironmentVariableW(L"NOBAD_FIND_RENDERER", renderer, 16) > 0 &&
      wcscmp(renderer, L"impeller") == 0;
  project.set_impeller_switch(impeller ? flutter::ImpellerSwitch::Enabled
                                       : flutter::ImpellerSwitch::Disabled);

  std::vector<std::string> command_line_arguments =
      GetCommandLineArguments();

  const bool bar = std::find(command_line_arguments.begin(),
                             command_line_arguments.end(),
                             "--bar") != command_line_arguments.end();

  // One main window and one bar per user session: a second start of the main window brings the running one to
  // the front and ends; a second bar just ends (the engine's bar hotkey shows the running one).
  // NOBAD_FIND_UI_ALLOW_SECOND=1 (development only) skips this, to run a second window next to a demo.
  wchar_t second[4] = {};
  const bool allow_second = GetEnvironmentVariableW(L"NOBAD_FIND_UI_ALLOW_SECOND", second, 4) > 0 &&
                            wcscmp(second, L"1") == 0;
  HANDLE single = allow_second ? nullptr
                               : CreateMutexW(nullptr, FALSE,
                                              bar ? L"Local\\NOBADFindUI-bar" : L"Local\\NOBADFindUI-main");
  if (single != nullptr && GetLastError() == ERROR_ALREADY_EXISTS) {
    if (!bar) {
      HWND other = FindWindowW(L"FLUTTER_RUNNER_WIN32_WINDOW", L"NOBAD Find");
      if (other != nullptr) {
        ShowWindow(other, IsIconic(other) ? SW_RESTORE : SW_SHOW);
        SetForegroundWindow(other);
      }
    }
    CloseHandle(single);
    ::CoUninitialize();
    return EXIT_SUCCESS;
  }

  project.set_dart_entrypoint_arguments(std::move(command_line_arguments));

  FlutterWindow window(project);
  window.SetPopup(bar);
  Win32Window::Point origin(80, 60);
  Win32Window::Size size = bar ? Win32Window::Size(640, 64)
                               : Win32Window::Size(1180, 760);  // client size; placed and clamped by Create
  if (!window.Create(bar ? L"NOBAD Find bar" : L"NOBAD Find", origin, size)) {
    return EXIT_FAILURE;
  }
  if (bar) {
    PlaceBar(window.GetHandle());  // before the first frame shows it
  }
  window.SetQuitOnClose(true);

  ::MSG msg;
  while (::GetMessage(&msg, nullptr, 0, 0)) {
    ::TranslateMessage(&msg);
    ::DispatchMessage(&msg);
  }

  ::CoUninitialize();
  return EXIT_SUCCESS;
}
