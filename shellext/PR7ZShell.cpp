// PR7ZShell.dll: Paragon PR7-Z's Explorer context menu (the counterpart of 7-Zip's 7-zip.dll).
//
// Explorer loads this DLL into itself when you right-click files, so it does as little as possible:
// it builds the menu (with the real file names, like 7-Zip) and, when an item is clicked, starts
// PR7-Z with the matching command line. All archive work happens in PR7-Z (Python) and 7z.exe.
//
// Settings (written by PR7-Z's Tools > Options, read on every right-click):
//   HKCU\Software\Paragon\PR7-Z\Shell
//     Command   REG_SZ     how to start PR7-Z, e.g. "C:\Tools\PR7-Z\PR7-Z.exe" (no menu if missing)
//     Icon      REG_SZ     .ico or .exe for the menu icon
//     Cascaded  REG_DWORD  1 = items in a "PR7-Z" submenu (default), 0 = straight in Explorer's menu
//     Items     REG_DWORD  bit mask of the items shown (bit order: enum Item below; default all)

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <shlwapi.h>
#include <wincodec.h>

#include <cwctype>
#include <new>
#include <string>
#include <vector>

// {ED2155D5-4754-4F17-A401-780852864C71}
static const CLSID CLSID_PR7ZMenu = {0xED2155D5, 0x4754, 0x4F17, {0xA4, 0x01, 0x78, 0x08, 0x52, 0x86, 0x4C, 0x71}};
// BHID_DataObject, defined here so the DLL doesn't depend on which SDK headers declare it.
static const GUID kBHID_DataObject = {0xB8C0BD9F, 0xED24, 0x455C, {0x83, 0xE6, 0xD5, 0x39, 0x0C, 0x4F, 0xE8, 0xC4}};

static HINSTANCE g_module = nullptr;
static LONG g_objects = 0;
static LONG g_locks = 0;

namespace pr7z {

enum Item {
    kOpen = 0, kOpenAs, kExtract, kExtractHere, kExtractTo, kTest, kAdd, kAddEmail,
    kAdd7z, kAdd7zEmail, kAddZip, kAddZipEmail, kHash, kItemCount
};
static const DWORD kAllItems = (1u << kItemCount) - 1;

struct Settings {
    std::wstring command, icon;
    bool cascaded = true;
    DWORD items = kAllItems;
};

// One menu entry: a label, and either a command (action + files) or a submenu.
struct Entry {
    std::wstring label;
    std::wstring action;            // e.g. --add-to "D:\x.7z"  (files are appended when launched)
    bool with_files = true;
    std::vector<Entry> children;
};

static const wchar_t* kArchiveExts[] = {
    L"7z", L"zip", L"rar", L"r00", L"tar", L"gz", L"tgz", L"bz2", L"tbz", L"tbz2", L"xz", L"txz", L"lzma", L"zst",
    L"tzst", L"wim", L"swm", L"esd", L"cab", L"iso", L"img", L"dmg", L"vhd", L"vhdx", L"vmdk", L"arj", L"lzh",
    L"lha", L"cpio", L"rpm", L"deb", L"z", L"taz", L"chm", L"msi", L"squashfs", L"xar", L"pkg", L"apfs", L"001",
    L"jar", L"xpi", L"apk", L"zipx"};

static std::wstring Lower(std::wstring s) {
    for (auto& c : s) c = (wchar_t)towlower(c);
    return s;
}

static std::wstring Trimmed(const std::wstring& p) {  // without trailing separators, but keep "D:\"
    std::wstring q = p;
    while (q.size() > 3 && (q.back() == L'\\' || q.back() == L'/')) q.pop_back();
    return q;
}

static std::wstring FileName(const std::wstring& p) {
    std::wstring q = Trimmed(p);
    size_t i = q.find_last_of(L"\\/");
    std::wstring n = i == std::wstring::npos ? q : q.substr(i + 1);
    return n;
}

static std::wstring Parent(const std::wstring& p) {
    std::wstring q = Trimmed(p);
    size_t i = q.find_last_of(L"\\/");
    if (i == std::wstring::npos) return L"";
    std::wstring r = q.substr(0, i);
    if (r.size() == 2 && r[1] == L':') r += L'\\';
    return r;
}

static std::wstring Join(const std::wstring& dir, const std::wstring& name) {
    if (dir.empty()) return name;
    return (dir.back() == L'\\' || dir.back() == L'/') ? dir + name : dir + L"\\" + name;
}

static bool SplitExt(const std::wstring& name, std::wstring& stem, std::wstring& ext) {
    size_t i = name.rfind(L'.');
    if (i == std::wstring::npos || i == 0) return false;  // ".bashrc" has no extension (as Python's Path.stem)
    stem = name.substr(0, i);
    ext = Lower(name.substr(i + 1));
    return true;
}

static bool AllDigits(const std::wstring& s) {
    if (s.empty()) return false;
    for (wchar_t c : s)
        if (c < L'0' || c > L'9') return false;
    return true;
}

static bool IsArchiveExt(const std::wstring& ext) {
    for (auto e : kArchiveExts)
        if (ext == e) return true;
    return AllDigits(ext) && ext.size() == 3;  // split volumes: .001 .002 ...
}

static bool IsDir(const std::wstring& p) {
    DWORD a = GetFileAttributesW(p.c_str());
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}

static bool Exists(const std::wstring& p) { return GetFileAttributesW(p.c_str()) != INVALID_FILE_ATTRIBUTES; }

// Same rule as operations.default_extract_dir: the archive's folder + its name without up to two
// archive extensions (x.7z -> x, x.tar.gz -> x, x.7z.001 -> x).
static std::wstring ExtractDir(const std::wstring& archive) {
    std::wstring name = FileName(archive);
    for (int k = 0; k < 2; ++k) {
        std::wstring stem, ext;
        if (SplitExt(name, stem, ext) && !stem.empty() && (IsArchiveExt(ext) || AllDigits(ext) || ext == L"tar"))
            name = stem;
    }
    return Join(Parent(archive), name);
}

// Same rule as add_dialog.default_archive_name: one item -> its name (files without their extension);
// several -> the folder they're in.
static std::wstring ArchiveBase(const std::vector<std::wstring>& files) {
    if (files.size() == 1) {
        std::wstring n = FileName(files[0]), stem, ext;
        if (IsDir(files[0])) return (n.size() == 3 && n[1] == L':') ? std::wstring(1, n[0]) : n;  // "D:\" -> "D"
        return SplitExt(n, stem, ext) ? stem : n;
    }
    std::wstring parent = FileName(Parent(files[0]));
    if (parent.empty() || (parent.size() <= 3 && parent[parent.size() > 1 ? 1 : 0] == L':')) return L"Archive";
    return parent;
}

// 7-Zip's naming: "name.7z", or "name_2.7z", "name_3.7z" ... when taken (or when it's one of the files).
static std::wstring UniqueArchive(const std::wstring& dir, const std::wstring& base, const std::wstring& ext,
                                  const std::vector<std::wstring>& files) {
    for (int n = 1; n < 10000; ++n) {
        std::wstring name = n == 1 ? base + L"." + ext : base + L"_" + std::to_wstring(n) + L"." + ext;
        std::wstring cand = Join(dir, name);
        bool clash = Exists(cand);
        for (auto& f : files)
            if (!clash && Lower(Trimmed(f)) == Lower(cand)) clash = true;
        if (!clash) return cand;
    }
    return Join(dir, base + L"." + ext);
}

// One argument quoted so CommandLineToArgvW / Python's argv give it back exactly
// (backslashes are only special before a quote: "D:\" must become "D:\\").
static std::wstring Quote(const std::wstring& a) {
    std::wstring r = L"\"";
    size_t bs = 0;
    for (wchar_t c : a) {
        if (c == L'\\') { ++bs; continue; }
        if (c == L'"') { r.append(bs * 2 + 1, L'\\'); r += L'"'; bs = 0; continue; }
        r.append(bs, L'\\');
        bs = 0;
        r += c;
    }
    r.append(bs * 2, L'\\');
    r += L'"';
    return r;
}

static std::vector<Entry> BuildMenu(const std::vector<std::wstring>& files, DWORD items) {
    std::vector<Entry> m;
    if (files.empty()) return m;
    auto on = [&](Item i) { return (items >> i) & 1u; };
    bool single = files.size() == 1, any_dir = false, all_archives = true;
    for (auto& f : files) {
        std::wstring stem, ext;
        if (IsDir(f)) { any_dir = true; all_archives = false; }
        else if (!SplitExt(FileName(f), stem, ext) || !IsArchiveExt(ext)) all_archives = false;
    }
    if (single && !any_dir) {
        if (on(kOpen)) m.push_back({L"Open archive", L"--open", true, {}});
        if (on(kOpenAs)) {
            Entry as{L"Open archive", L"", false, {}};
            for (auto t : {L"*", L"#", L"#:e", L"7z", L"zip", L"cab", L"rar", L"iso", L"tar", L"wim"})
                as.children.push_back({t, std::wstring(L"--open-as ") + Quote(t), true, {}});
            m.push_back(as);
        }
    }
    if (all_archives) {
        if (on(kExtract)) m.push_back({L"Extract files...", L"--extract", true, {}});
        if (on(kExtractHere)) m.push_back({L"Extract Here", L"--extract-here", true, {}});
        if (on(kExtractTo)) {
            if (single) {
                std::wstring dir = ExtractDir(files[0]);
                m.push_back({L"Extract to \"" + FileName(dir) + L"\\\"", L"--extract-into " + Quote(dir), true, {}});
            } else {
                m.push_back({L"Extract to \"*\\\"", L"--extract-to", true, {}});
            }
        }
        if (on(kTest)) m.push_back({L"Test archive", L"--test", true, {}});
    }
    std::wstring dir = Parent(files[0]), base = ArchiveBase(files);
    if (on(kAdd)) m.push_back({L"Add to archive...", L"--add", true, {}});
    if (on(kAddEmail)) m.push_back({L"Compress and email...", L"--add-email", true, {}});
    for (auto ext : {L"7z", L"zip"}) {
        bool is7z = std::wstring(ext) == L"7z";
        std::wstring arc = UniqueArchive(dir, base, ext, files), name = FileName(arc);
        if (on(is7z ? kAdd7z : kAddZip))
            m.push_back({L"Add to \"" + name + L"\"", L"--add-to " + Quote(arc), true, {}});
        if (on(is7z ? kAdd7zEmail : kAddZipEmail))
            m.push_back({L"Compress to \"" + name + L"\" and email", L"--add-to-email " + Quote(name), true, {}});
    }
    if (on(kHash)) {
        Entry h{L"CRC SHA", L"", false, {}};
        const wchar_t* hashes[][2] = {{L"CRC-32", L"CRC32"}, {L"CRC-64", L"CRC64"}, {L"XXH64", L"XXH64"},
                                      {L"MD5", L"MD5"},       {L"SHA-1", L"SHA1"},   {L"SHA-256", L"SHA256"},
                                      {L"SHA-512", L"SHA512"}, {L"BLAKE2sp", L"BLAKE2sp"}, {L"*", L"*"}};
        for (auto& x : hashes) h.children.push_back({x[0], std::wstring(L"--hash:") + x[1], true, {}});
        m.push_back(h);
    }
    return m;
}

static Settings ReadSettings() {
    Settings s;
    HKEY k;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\Paragon\\PR7-Z\\Shell", 0, KEY_READ, &k) != ERROR_SUCCESS)
        return s;
    wchar_t buf[2048];
    DWORD size = sizeof(buf), type = 0, dw = 0;
    if (RegQueryValueExW(k, L"Command", nullptr, &type, (BYTE*)buf, &size) == ERROR_SUCCESS && type == REG_SZ)
        s.command.assign(buf, wcsnlen(buf, size / sizeof(wchar_t)));
    size = sizeof(buf);
    if (RegQueryValueExW(k, L"Icon", nullptr, &type, (BYTE*)buf, &size) == ERROR_SUCCESS && type == REG_SZ)
        s.icon.assign(buf, wcsnlen(buf, size / sizeof(wchar_t)));
    size = sizeof(dw);
    if (RegQueryValueExW(k, L"Cascaded", nullptr, &type, (BYTE*)&dw, &size) == ERROR_SUCCESS && type == REG_DWORD)
        s.cascaded = dw != 0;
    size = sizeof(dw);
    if (RegQueryValueExW(k, L"Items", nullptr, &type, (BYTE*)&dw, &size) == ERROR_SUCCESS && type == REG_DWORD)
        s.items = dw;
    RegCloseKey(k);
    return s;
}

// The full command line for a clicked entry. Very long selections (Windows' limit is 32 767
// characters) go through a temporary list file that PR7-Z reads and deletes, as 7-Zip does.
static std::wstring CommandLine(const std::wstring& command, const Entry& e, const std::vector<std::wstring>& files) {
    std::wstring cmd = command + L" " + e.action;
    if (!e.with_files) return cmd;
    std::wstring list;
    for (auto& f : files) list += L" " + Quote(f);
    if (cmd.size() + list.size() < 30000) return cmd + list;
    wchar_t tmp[MAX_PATH], path[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    swprintf(path, MAX_PATH, L"%spr7z-list-%lu-%lu.txt", tmp, GetCurrentProcessId(), GetTickCount());
    HANDLE h = CreateFileW(path, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_TEMPORARY, nullptr);
    if (h == INVALID_HANDLE_VALUE) return cmd + list;
    for (auto& f : files) {
        std::wstring line = f + L"\n";
        int n = WideCharToMultiByte(CP_UTF8, 0, line.c_str(), (int)line.size(), nullptr, 0, nullptr, nullptr);
        std::string utf8(n, '\0');
        WideCharToMultiByte(CP_UTF8, 0, line.c_str(), (int)line.size(), &utf8[0], n, nullptr, nullptr);
        DWORD written;
        WriteFile(h, utf8.data(), (DWORD)utf8.size(), &written, nullptr);
    }
    CloseHandle(h);
    return cmd + L" --files-from " + Quote(path);
}

static bool Launch(const std::wstring& cmdline, const std::wstring& cwd) {
    std::vector<wchar_t> buf(cmdline.begin(), cmdline.end());
    buf.push_back(L'\0');
    STARTUPINFOW si = {};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi = {};
    BOOL ok = CreateProcessW(nullptr, buf.data(), nullptr, nullptr, FALSE, 0, nullptr,
                             cwd.empty() || !IsDir(cwd) ? nullptr : cwd.c_str(), &si, &pi);
    if (ok) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    return ok != FALSE;
}

// The menu icon: PR7-Z's icon as a 32-bit premultiplied bitmap (what menus need for alpha).
static HBITMAP IconBitmap(const std::wstring& source) {
    if (source.empty()) return nullptr;
    int cx = GetSystemMetrics(SM_CXSMICON), cy = GetSystemMetrics(SM_CYSMICON);
    HICON icon = nullptr;
    if (Lower(source).size() > 4 && Lower(source).compare(source.size() - 4, 4, L".ico") == 0)
        icon = (HICON)LoadImageW(nullptr, source.c_str(), IMAGE_ICON, cx, cy, LR_LOADFROMFILE);
    else
        SHDefExtractIconW(source.c_str(), 0, 0, nullptr, &icon, MAKELONG(cx, cx));
    if (!icon) return nullptr;
    HBITMAP result = nullptr;
    IWICImagingFactory* factory = nullptr;
    IWICBitmap* bitmap = nullptr;
    IWICFormatConverter* conv = nullptr;
    if (SUCCEEDED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory))) &&
        SUCCEEDED(factory->CreateBitmapFromHICON(icon, &bitmap)) &&
        SUCCEEDED(factory->CreateFormatConverter(&conv)) &&
        SUCCEEDED(conv->Initialize(bitmap, GUID_WICPixelFormat32bppPBGRA, WICBitmapDitherTypeNone, nullptr, 0.0,
                                   WICBitmapPaletteTypeCustom))) {
        UINT w = 0, h = 0;
        conv->GetSize(&w, &h);
        BITMAPINFO bi = {};
        bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
        bi.bmiHeader.biWidth = (LONG)w;
        bi.bmiHeader.biHeight = -(LONG)h;  // top-down
        bi.bmiHeader.biPlanes = 1;
        bi.bmiHeader.biBitCount = 32;
        bi.bmiHeader.biCompression = BI_RGB;
        void* bits = nullptr;
        result = CreateDIBSection(nullptr, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
        if (result && FAILED(conv->CopyPixels(nullptr, w * 4, w * h * 4, (BYTE*)bits))) {
            DeleteObject(result);
            result = nullptr;
        }
    }
    if (conv) conv->Release();
    if (bitmap) bitmap->Release();
    if (factory) factory->Release();
    DestroyIcon(icon);
    return result;
}

// ------------------------------------------------------------------------------------------ COM
class ContextMenu final : public IShellExtInit, public IContextMenu {
public:
    ContextMenu() { InterlockedIncrement(&g_objects); }

    // IUnknown
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (riid == IID_IUnknown || riid == IID_IShellExtInit) *ppv = static_cast<IShellExtInit*>(this);
        else if (riid == IID_IContextMenu) *ppv = static_cast<IContextMenu*>(this);
        else { *ppv = nullptr; return E_NOINTERFACE; }
        AddRef();
        return S_OK;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override {
        LONG r = InterlockedDecrement(&refs_);
        if (r == 0) delete this;
        return r;
    }

    // IShellExtInit: remember the selected files.
    IFACEMETHODIMP Initialize(PCIDLIST_ABSOLUTE, IDataObject* data, HKEY) override {
        files_.clear();
        if (!data) return E_INVALIDARG;
        IShellItemArray* arr = nullptr;
        if (SUCCEEDED(SHCreateShellItemArrayFromDataObject(data, IID_PPV_ARGS(&arr)))) {
            DWORD n = 0;
            arr->GetCount(&n);
            for (DWORD i = 0; i < n; ++i) {
                IShellItem* item = nullptr;
                if (SUCCEEDED(arr->GetItemAt(i, &item))) {
                    PWSTR path = nullptr;
                    if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &path))) {
                        files_.push_back(path);
                        CoTaskMemFree(path);
                    }
                    item->Release();
                }
            }
            arr->Release();
        }
        if (files_.empty()) {  // older hosts: the classic file list (CF_HDROP)
            FORMATETC fe = {CF_HDROP, nullptr, DVASPECT_CONTENT, -1, TYMED_HGLOBAL};
            STGMEDIUM st = {};
            if (SUCCEEDED(data->GetData(&fe, &st))) {
                HDROP drop = (HDROP)GlobalLock(st.hGlobal);
                if (drop) {
                    UINT n = DragQueryFileW(drop, 0xFFFFFFFF, nullptr, 0);
                    for (UINT i = 0; i < n; ++i) {
                        wchar_t p[32768];
                        if (DragQueryFileW(drop, i, p, 32768)) files_.push_back(p);
                    }
                    GlobalUnlock(st.hGlobal);
                }
                ReleaseStgMedium(&st);
            }
        }
        return files_.empty() ? E_FAIL : S_OK;
    }

    // IContextMenu
    IFACEMETHODIMP QueryContextMenu(HMENU menu, UINT index, UINT first, UINT last, UINT flags) override {
        if (flags & CMF_DEFAULTONLY) return MAKE_HRESULT(SEVERITY_SUCCESS, FACILITY_NULL, 0);
        settings_ = ReadSettings();
        commands_.clear();
        if (settings_.command.empty()) return MAKE_HRESULT(SEVERITY_SUCCESS, FACILITY_NULL, 0);
        std::vector<Entry> entries = BuildMenu(files_, settings_.items);
        if (entries.empty()) return MAKE_HRESULT(SEVERITY_SUCCESS, FACILITY_NULL, 0);
        if (!bitmap_) bitmap_ = IconBitmap(settings_.icon);
        UINT id = first, pos = index;
        InsertMenuW(menu, pos++, MF_BYPOSITION | MF_SEPARATOR, 0, nullptr);
        if (settings_.cascaded) {
            HMENU sub = CreatePopupMenu();
            UINT subpos = 0;
            Fill(sub, subpos, entries, id, last);
            MENUITEMINFOW mii = {};
            mii.cbSize = sizeof(mii);
            mii.fMask = MIIM_SUBMENU | MIIM_STRING | (bitmap_ ? MIIM_BITMAP : 0);
            mii.hSubMenu = sub;
            mii.dwTypeData = const_cast<LPWSTR>(L"PR7-Z");
            mii.hbmpItem = bitmap_;
            InsertMenuItemW(menu, pos++, TRUE, &mii);
        } else {
            UINT start = pos;
            Fill(menu, pos, entries, id, last);
            if (bitmap_) {
                MENUITEMINFOW mii = {};
            mii.cbSize = sizeof(mii);
                mii.fMask = MIIM_BITMAP;
                mii.hbmpItem = bitmap_;
                SetMenuItemInfoW(menu, start, TRUE, &mii);
            }
        }
        InsertMenuW(menu, pos++, MF_BYPOSITION | MF_SEPARATOR, 0, nullptr);
        return MAKE_HRESULT(SEVERITY_SUCCESS, FACILITY_NULL, id - first);
    }

    IFACEMETHODIMP InvokeCommand(CMINVOKECOMMANDINFO* info) override {
        if (!info || HIWORD(info->lpVerb) != 0) return E_INVALIDARG;  // only our ids, no verb strings
        UINT offset = LOWORD(info->lpVerb);
        if (offset >= commands_.size()) return E_INVALIDARG;
        std::wstring cwd = files_.empty() ? L"" : (IsDir(files_[0]) ? Parent(files_[0]) : Parent(files_[0]));
        return Launch(CommandLineFor(offset), cwd) ? S_OK : HRESULT_FROM_WIN32(GetLastError());
    }

    IFACEMETHODIMP GetCommandString(UINT_PTR id, UINT type, UINT*, CHAR* name, UINT cch) override {
        if (id >= commands_.size()) return E_INVALIDARG;
        if (type == GCS_HELPTEXTW) {
            lstrcpynW(reinterpret_cast<LPWSTR>(name), commands_[id].label.c_str(), (int)cch);
            return S_OK;
        }
        if (type == GCS_VALIDATEW || type == GCS_VALIDATEA) return S_OK;
        return E_NOTIMPL;
    }

    // For the self-test: the command line an entry would run.
    std::wstring CommandLineFor(UINT offset) const {
        return CommandLine(settings_.command, commands_[offset], files_);
    }
    size_t CommandCount() const { return commands_.size(); }

private:
    ~ContextMenu() {
        if (bitmap_) DeleteObject(bitmap_);
        InterlockedDecrement(&g_objects);
    }

    void Fill(HMENU menu, UINT& pos, const std::vector<Entry>& entries, UINT& id, UINT last) {
        for (auto& e : entries) {
            if (!e.children.empty()) {
                HMENU sub = CreatePopupMenu();
                UINT subpos = 0;
                Fill(sub, subpos, e.children, id, last);
                InsertMenuW(menu, pos++, MF_BYPOSITION | MF_POPUP | MF_STRING, (UINT_PTR)sub, e.label.c_str());
                continue;
            }
            if (id > last) return;
            InsertMenuW(menu, pos++, MF_BYPOSITION | MF_STRING, id++, e.label.c_str());
            commands_.push_back(e);
        }
    }

    LONG refs_ = 1;
    std::vector<std::wstring> files_;
    std::vector<Entry> commands_;  // index = id offset
    Settings settings_;
    HBITMAP bitmap_ = nullptr;
};

class Factory final : public IClassFactory {
public:
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (riid == IID_IUnknown || riid == IID_IClassFactory) {
            *ppv = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override {
        LONG r = InterlockedDecrement(&refs_);
        if (r == 0) delete this;
        return r;
    }
    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** ppv) override {
        if (outer) return CLASS_E_NOAGGREGATION;
        ContextMenu* m = new (std::nothrow) ContextMenu();
        if (!m) return E_OUTOFMEMORY;
        HRESULT hr = m->QueryInterface(riid, ppv);
        m->Release();
        return hr;
    }
    IFACEMETHODIMP LockServer(BOOL lock) override {
        lock ? InterlockedIncrement(&g_locks) : InterlockedDecrement(&g_locks);
        return S_OK;
    }

private:
    LONG refs_ = 1;
};

// Walks a built menu into text lines for the self-test: "depth<TAB>label" or "depth<TAB>label<TAB>#id".
static void DumpMenu(HMENU menu, int depth, std::wstring& out) {
    int n = GetMenuItemCount(menu);
    for (int i = 0; i < n; ++i) {
        wchar_t text[512] = L"";
        MENUITEMINFOW mii = {};
        mii.cbSize = sizeof(mii);
        mii.fMask = MIIM_FTYPE | MIIM_ID | MIIM_SUBMENU | MIIM_STRING;
        mii.dwTypeData = text;
        mii.cch = 511;
        if (!GetMenuItemInfoW(menu, i, TRUE, &mii)) continue;
        out += std::to_wstring(depth) + L"\t";
        if (mii.fType & MFT_SEPARATOR) { out += L"-\n"; continue; }
        out += text;
        if (mii.hSubMenu) { out += L"\n"; DumpMenu(mii.hSubMenu, depth + 1, out); }
        else out += L"\t#" + std::to_wstring(mii.wID) + L"\n";
    }
}

}  // namespace pr7z

// ------------------------------------------------------------------------------------------ exports
extern "C" BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = inst;
        DisableThreadLibraryCalls(inst);
    }
    return TRUE;
}

STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    *ppv = nullptr;
    if (clsid != CLSID_PR7ZMenu) return CLASS_E_CLASSNOTAVAILABLE;
    pr7z::Factory* f = new (std::nothrow) pr7z::Factory();
    if (!f) return E_OUTOFMEMORY;
    HRESULT hr = f->QueryInterface(riid, ppv);
    f->Release();
    return hr;
}

STDAPI DllCanUnloadNow() { return (g_objects == 0 && g_locks == 0) ? S_OK : S_FALSE; }

// Self-test for PR7-Z's tests (not used by Explorer): runs the same path Explorer does for the given
// files (newline separated): a shell data object, IShellExtInit::Initialize, QueryContextMenu, then
// writes the menu (DumpMenu lines) and each item's command line ("cmd<TAB>#id<TAB>command") to `out`.
// Returns the number of characters written, or a negative HRESULT-ish code on failure.
extern "C" int PR7Z_SelfTest(const wchar_t* files_nl, wchar_t* out, int out_len) {
    using namespace pr7z;
    HRESULT co = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    std::vector<std::wstring> files;
    std::wstring cur;
    for (const wchar_t* p = files_nl; p && *p; ++p) {
        if (*p == L'\n') { if (!cur.empty()) files.push_back(cur); cur.clear(); }
        else cur += *p;
    }
    if (!cur.empty()) files.push_back(cur);
    std::vector<PIDLIST_ABSOLUTE> pidls;
    for (auto& f : files) {
        PIDLIST_ABSOLUTE pidl = nullptr;
        if (FAILED(SHParseDisplayName(f.c_str(), nullptr, &pidl, 0, nullptr))) return -2;
        pidls.push_back(pidl);
    }
    int result = -3;
    IShellItemArray* arr = nullptr;
    IDataObject* data = nullptr;
    IClassFactory* cf = nullptr;
    IShellExtInit* init = nullptr;
    IContextMenu* cm = nullptr;
    HMENU menu = nullptr;
    if (SUCCEEDED(SHCreateShellItemArrayFromIDLists((UINT)pidls.size(), (PCIDLIST_ABSOLUTE_ARRAY)pidls.data(), &arr)) &&
        SUCCEEDED(arr->BindToHandler(nullptr, kBHID_DataObject, IID_PPV_ARGS(&data))) &&
        SUCCEEDED(DllGetClassObject(CLSID_PR7ZMenu, IID_IClassFactory, (void**)&cf)) &&
        SUCCEEDED(cf->CreateInstance(nullptr, IID_IShellExtInit, (void**)&init)) &&
        SUCCEEDED(init->Initialize(nullptr, data, nullptr)) &&
        SUCCEEDED(init->QueryInterface(IID_IContextMenu, (void**)&cm))) {
        menu = CreatePopupMenu();
        HRESULT hr = cm->QueryContextMenu(menu, 0, 1, 0x7FFF, CMF_NORMAL);
        std::wstring text;
        DumpMenu(menu, 0, text);
        auto* impl = static_cast<ContextMenu*>(init);
        for (UINT i = 0; i < impl->CommandCount(); ++i)
            text += L"cmd\t#" + std::to_wstring(i + 1) + L"\t" + impl->CommandLineFor(i) + L"\n";
        text += L"ids\t" + std::to_wstring(HRESULT_CODE(hr)) + L"\n";
        if ((int)text.size() < out_len) {
            lstrcpynW(out, text.c_str(), out_len);
            result = (int)text.size();
        } else {
            result = -4;
        }
    }
    if (menu) DestroyMenu(menu);
    if (cm) cm->Release();
    if (init) init->Release();
    if (cf) cf->Release();
    if (data) data->Release();
    if (arr) arr->Release();
    for (auto p : pidls) CoTaskMemFree(p);
    if (SUCCEEDED(co)) CoUninitialize();
    return result;
}
