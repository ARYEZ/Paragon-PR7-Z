# PR7ZShell.dll, PR7-Z's Explorer context menu.
#   cmake -S shellext -B shellext/build -A x64 && cmake --build shellext/build --config Release
cmake_minimum_required(VERSION 3.20)
project(PR7ZShell CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Static C++ runtime: Explorer loads this DLL, which then needs no Visual C++ redistributable.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
add_library(PR7ZShell SHARED PR7ZShell.cpp PR7ZShell.def)
target_compile_definitions(PR7ZShell PRIVATE UNICODE _UNICODE NOMINMAX)
if(MSVC)
  target_compile_options(PR7ZShell PRIVATE /W4 /permissive-)
endif()
target_link_libraries(PR7ZShell PRIVATE shell32 shlwapi ole32 oleaut32 user32 gdi32 advapi32 windowscodecs uuid)
