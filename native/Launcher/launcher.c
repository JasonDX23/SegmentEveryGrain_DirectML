#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE previous,LPWSTR arguments,int show) {
    wchar_t directory[32768],target[32768],working[32768];
    DWORD length=GetModuleFileNameW(NULL,directory,32768);
    if(!length||length>=32768)return 1;
    wchar_t *slash=wcsrchr(directory,L'\\');if(!slash)return 1;*slash=0;
    int count=0;LPWSTR *parts=CommandLineToArgvW(GetCommandLineW(),&count);
    BOOL setup=count>1&&wcscmp(parts[1],L"--setup")==0;
    if(parts)LocalFree(parts);
    if(setup) {
        _snwprintf(target,32768,L"%ls\\Machine Setup.exe",directory);
        wcscpy(working,directory);
    } else {
        _snwprintf(target,32768,L"%ls\\WinUI\\SegmentEveryGrain.exe",directory);
        _snwprintf(working,32768,L"%ls\\WinUI",directory);
    }
    HINSTANCE result=ShellExecuteW(NULL,L"open",target,arguments,working,SW_SHOWNORMAL);
    if((INT_PTR)result<=32) {
        MessageBoxW(NULL,L"The application files could not be opened. Keep the WinUI folder next to this launcher, or rebuild with native\\Build.ps1.",L"Segment Every Grain",MB_OK|MB_ICONERROR);
        return 1;
    }
    return 0;
}
