RED checkpoint for the 2026-08-02 Windows Task Center field crash.

Expected failing assertions before the production fix:

- TaskCenterPage.xaml does not explicitly declare Mode=OneWay for Priority and TimeoutSeconds Run.Text bindings.
- App.xaml.cs does not register, log or contain DispatcherUnhandledException.

This file exists only to make the RED checkpoint explicit while hosted Windows runners are unavailable. The executable contract remains test_phase23_task_center_crash_regression.py.
