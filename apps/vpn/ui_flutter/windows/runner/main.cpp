#include <flutter/dart_project.h>
#include <flutter/flutter_view_controller.h>
#include <flutter_windows.h>
#include <windows.h>

#include <algorithm>
#include <cwchar>

#include "flutter_window.h"
#include "utils.h"
#include "window_geometry.h"

// NOBAD VPN's window. It runs as the signed-in user, never elevated: the engine (NobadVPN.exe, elevated) owns the
// tunnel, the firewall rules and the tray icon, and this program only talks to it over the engine pipe.
//
// No arguments: the main window. --mini: the tray pop-up, a frameless window near the notification area.

// The pop-up's size in logical pixels (lib/platform/window.dart MiniSize has the same numbers).
static const int kMiniWidth = 320;
static const int kMiniHeight = 392;

// Next to the tray: the corner of the work area where the taskbar is, on the monitor with the mouse (a tray click
// leaves it there). Taskbar at the bottom or top: the right end; at the left or right: the bottom end.
static void PlaceMini(HWND hwnd) {
  POINT pt{};
  GetCursorPos(&pt);
  HMONITOR monitor = MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST);
  MONITORINFO info{};
  info.cbSize = sizeof(info);
  if (!GetMonitorInfo(monitor, &info)) {
    return;
  }
  const double scale = FlutterDesktopGetDpiForMonitor(monitor) / 96.0;
  const RECT& m = info.rcMonitor;
  const RECT& r = info.rcWork;
  const int w = static_cast<int>(kMiniWidth * scale + 0.5);
  const int h = static_cast<int>(kMiniHeight * scale + 0.5);
  const int gap = static_cast<int>(12 * scale + 0.5);
  int x = r.right - w - gap;
  int y = r.bottom - h - gap;
  if (r.top > m.top) {  // taskbar on top
    y = r.top + gap;
  } else if (r.left > m.left) {  // taskbar on the left
    x = r.left + gap;
  }
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

  // Skia, not Impeller: NOBAD Find measured ~0.2 s instead of ~0.9 s to start and ~50 MB less on an Intel iGPU
  // (apps/find/docs/measurements.md). NOBAD_VPN_RENDERER=impeller switches back, for measuring.
  wchar_t renderer[16] = {};
  const bool impeller =
      GetEnvironmentVariableW(L"NOBAD_VPN_RENDERER", renderer, 16) > 0 &&
      wcscmp(renderer, L"impeller") == 0;
  project.set_impeller_switch(impeller ? flutter::ImpellerSwitch::Enabled
                                       : flutter::ImpellerSwitch::Disabled);

  std::vector<std::string> command_line_arguments =
      GetCommandLineArguments();

  const bool mini = std::find(command_line_arguments.begin(),
                              command_line_arguments.end(),
                              "--mini") != command_line_arguments.end();

  // One main window and one pop-up per user session: a second start of the main window brings the running one to
  // the front and ends; a second pop-up just ends (the engine's tray click shows the running one over the pipe).
  // NOBAD_VPN_UI_ALLOW_SECOND=1 (development only) skips this, to run a second window next to a demo.
  wchar_t second[4] = {};
  const bool allow_second = GetEnvironmentVariableW(L"NOBAD_VPN_UI_ALLOW_SECOND", second, 4) > 0 &&
                            wcscmp(second, L"1") == 0;
  HANDLE single = allow_second ? nullptr
                               : CreateMutexW(nullptr, FALSE,
                                              mini ? L"Local\\NOBADVPNUI-mini" : L"Local\\NOBADVPNUI-main");
  if (single != nullptr && GetLastError() == ERROR_ALREADY_EXISTS) {
    if (!mini) {
      HWND other = FindWindowW(L"FLUTTER_RUNNER_WIN32_WINDOW", L"NOBAD VPN");
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
  window.SetPopup(mini);
  Win32Window::Point origin(80, 60);
  Win32Window::Size size = mini ? Win32Window::Size(kMiniWidth, kMiniHeight)
                                : Win32Window::Size(geometry::kDefaultWidth, geometry::kDefaultHeight);
  if (!window.Create(mini ? L"NOBAD VPN quick view" : L"NOBAD VPN", origin, size)) {
    return EXIT_FAILURE;
  }
  if (mini) {
    PlaceMini(window.GetHandle());  // before the first frame shows it
  } else {
    geometry::Restore(window.GetHandle());  // the remembered size and place, within the limits
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
