// Lovense HUD — compact (avoid Stack-Heap Collision)
// Touch=menu | /7 help | Setup=token/URL | textures switch with status
// PC: panel ON + HTTPS tunnel. GUI can fill BASE_URL + TOKEN.

string  BASE_URL = "http://192.168.1.10:8787";
string  TOKEN    = "WKLEJ_TOKEN_Z_GUI";
integer CHAT_CHANNEL = 7;
float   DEFAULT_TIME = 4.0;
string  NOTECARD_NAME = "lovense.cfg";
integer HUD_ATTACH_POINT = 38;

// Status textures (upload PNGs → paste UUIDs)
key TEX_OFFLINE = "d935f61f-6a11-db27-dcaa-43d337291ac1";
key TEX_ONLINE  = "d18a233f-3c4a-96e9-8f55-e7de49884bd6";
key TEX_BUSY    = "94199f1e-0294-6655-eb9f-3c3e13014756";
key TEX_ERROR   = "a5174b3f-4f59-057e-4efe-355e2579eece";

integer PROMPT_NONE = 0;
integer PROMPT_TOKEN = 1;
integer PROMPT_URL = 2;

key gReq;
key gNoteQuery;
integer gListen;
integer gMenuChan;
integer gMenuListen;
integer gLine;
integer gConnected;
string  gLastMsg;
integer gBusy;
integer gAttachTried;
key gLastFaceTex;
integer gPromptKind;
integer gNotePending;
integer gHttpCode; // last HTTP status for error face

string TrimSlash(string u)
{
    integer n = llStringLength(u);
    while (n > 0 && llGetSubString(u, n - 1, n - 1) == "/")
    {
        u = llGetSubString(u, 0, n - 2);
        n = llStringLength(u);
    }
    return u;
}

string UrlJoin(string path, string query)
{
    string u = TrimSlash(BASE_URL);
    if (llGetSubString(path, 0, 0) != "/") path = "/" + path;
    if (query != "") return u + path + "?" + query;
    return u + path;
}

integer TokenMissing()
{
    return (TOKEN == "" || TOKEN == "WKLEJ_TOKEN_Z_GUI");
}

integer BaseUrlNeedsSetup()
{
    string u = llToLower(TrimSlash(BASE_URL));
    if (u == "") return TRUE;
    if (llSubStringIndex(u, "127.0.0.1") >= 0) return TRUE;
    if (llSubStringIndex(u, "localhost") >= 0) return TRUE;
    if (llSubStringIndex(u, "192.168.1.10") >= 0) return TRUE;
    if (llSubStringIndex(u, "xxxx.") >= 0) return TRUE;
    return FALSE;
}

// face 0 texture by status
Look()
{
    llSetText("", ZERO_VECTOR, 0.0);
    key tex = TEX_OFFLINE;
    float glow = 0.04;
    if (gHttpCode == 401 || gHttpCode == 403 || (gHttpCode >= 400 && gHttpCode != 0))
    {
        tex = TEX_ERROR;
        glow = 0.08;
    }
    else if (gBusy)
    {
        tex = TEX_BUSY;
        glow = 0.14;
    }
    else if (gConnected)
    {
        tex = TEX_ONLINE;
        glow = 0.10;
    }
    if (tex != gLastFaceTex)
    {
        gLastFaceTex = tex;
        llSetLinkPrimitiveParamsFast(LINK_THIS, [
            PRIM_TEXTURE, 0, tex, <1,1,0>, ZERO_VECTOR, 0.0,
            PRIM_TEXTURE, 2, tex, <1,1,0>, ZERO_VECTOR, 0.0,
            PRIM_COLOR, 0, <1,1,1>, 1.0,
            PRIM_COLOR, 2, <0.9,0.9,0.95>, 1.0,
            PRIM_FULLBRIGHT, 0, TRUE,
            PRIM_FULLBRIGHT, 2, TRUE
        ]);
    }
    llSetLinkPrimitiveParamsFast(LINK_THIS, [
        PRIM_GLOW, 0, glow,
        PRIM_GLOW, 2, glow * 0.3
    ]);
}

SetupHud()
{
    llSetObjectName("Lovense HUD");
    llSetObjectDesc("touch=menu /7 help");
    llSetLinkPrimitiveParamsFast(LINK_THIS, [
        PRIM_TYPE, PRIM_TYPE_BOX, PRIM_HOLE_DEFAULT,
            <0,1,0>, 0.0, ZERO_VECTOR, <1,1,0>, ZERO_VECTOR,
        PRIM_SIZE, <0.22, 0.12, 0.014>,
        PRIM_PHYSICS, FALSE,
        PRIM_PHANTOM, FALSE,
        PRIM_COLOR, ALL_SIDES, <0.3,0.05,0.12>, 1.0,
        PRIM_TEXTURE, ALL_SIDES, TEXTURE_BLANK, <1,1,0>, ZERO_VECTOR, 0.0,
        PRIM_FULLBRIGHT, ALL_SIDES, FALSE,
        PRIM_GLOW, ALL_SIDES, 0.0
    ]);
    llSetClickAction(CLICK_ACTION_TOUCH);
    gLastFaceTex = NULL_KEY;
    Look();
}

OpenListen()
{
    gMenuChan = 0x80000000 | (integer)llFrand(0x7FFFFFFF);
    llListenRemove(gMenuListen);
    gMenuListen = llListen(gMenuChan, "", llGetOwner(), "");
}

string ExtractToken(string s)
{
    integer i = llSubStringIndex(s, "/r/");
    if (i >= 0)
    {
        string r = llGetSubString(s, i + 3, -1);
        integer c = llSubStringIndex(r, "?");
        if (c >= 0) r = llGetSubString(r, 0, c - 1);
        c = llSubStringIndex(r, "/");
        if (c >= 0) r = llGetSubString(r, 0, c - 1);
        return llStringTrim(r, STRING_TRIM);
    }
    i = llSubStringIndex(llToLower(s), "token=");
    if (i >= 0)
    {
        string r = llGetSubString(s, i + 6, -1);
        integer a = llSubStringIndex(r, "&");
        if (a >= 0) r = llGetSubString(r, 0, a - 1);
        return llStringTrim(r, STRING_TRIM);
    }
    return s;
}

string ExtractBase(string s)
{
    s = llStringTrim(s, STRING_TRIM);
    if (llSubStringIndex(s, "http://") != 0 && llSubStringIndex(s, "https://") != 0)
        return TrimSlash(s);
    integer r = llSubStringIndex(s, "/r/");
    if (r >= 0) return TrimSlash(llGetSubString(s, 0, r - 1));
    integer p = llSubStringIndex(s, "/sl");
    if (p >= 0) return TrimSlash(llGetSubString(s, 0, p - 1));
    p = llSubStringIndex(s, "/panel");
    if (p >= 0) return TrimSlash(llGetSubString(s, 0, p - 1));
    p = llSubStringIndex(s, "?");
    if (p >= 0) s = llGetSubString(s, 0, p - 1);
    return TrimSlash(s);
}

PromptToken()
{
    OpenListen();
    gPromptKind = PROMPT_TOKEN;
    llTextBox(llGetOwner(),
        "Lovense HUD — TOKEN\nPaste token OR full panel link (.../r/TOKEN).\nEmpty=cancel.",
        gMenuChan);
}

PromptUrl()
{
    OpenListen();
    gPromptKind = PROMPT_URL;
    string cur = TrimSlash(BASE_URL);
    if (cur == "") cur = "(none)";
    llTextBox(llGetOwner(),
        "Lovense HUD — BASE URL\nPaste HTTPS tunnel or full .../r/TOKEN link.\nNow: " + cur,
        gMenuChan);
}

integer MaybeSetup()
{
    if (TokenMissing()) { PromptToken(); return TRUE; }
    if (BaseUrlNeedsSetup()) { PromptUrl(); return TRUE; }
    return FALSE;
}

HandlePrompt(string msg)
{
    integer kind = gPromptKind;
    gPromptKind = PROMPT_NONE;
    msg = llStringTrim(msg, STRING_TRIM);
    if (msg == "")
    {
        llOwnerSay("Setup cancelled.");
        return;
    }
    integer link = (llSubStringIndex(msg, "http") == 0
        || llSubStringIndex(msg, "/r/") >= 0
        || llSubStringIndex(llToLower(msg), "token=") >= 0);
    if (kind == PROMPT_TOKEN)
    {
        if (link)
        {
            string b = ExtractBase(msg);
            string t = ExtractToken(msg);
            if (t != "") TOKEN = t;
            if (llSubStringIndex(b, "http") == 0)
            {
                BASE_URL = b;
                llOwnerSay("TOKEN+URL OK. BASE=" + BASE_URL);
                DoGet("/sl/status", "");
                return;
            }
        }
        TOKEN = ExtractToken(msg);
        llOwnerSay("TOKEN saved (" + (string)llStringLength(TOKEN) + " ch). Paste URL next.");
        PromptUrl();
        return;
    }
    if (kind == PROMPT_URL)
    {
        if (llSubStringIndex(msg, "/r/") >= 0)
        {
            string t = ExtractToken(msg);
            if (llStringLength(t) > 4) TOKEN = t;
        }
        BASE_URL = ExtractBase(msg);
        llOwnerSay("BASE_URL=" + BASE_URL);
        if (TokenMissing()) PromptToken();
        else DoGet("/sl/status", "");
    }
}

DoGet(string path, string query)
{
    if (TokenMissing())
    {
        llOwnerSay("No TOKEN.");
        PromptToken();
        return;
    }
    string q = "token=" + llEscapeURL(TOKEN);
    if (query != "") q += "&" + query;
    gBusy = TRUE;
    Look();
    gReq = llHTTPRequest(UrlJoin(path, q),
        [HTTP_METHOD, "GET", HTTP_VERBOSE_THROTTLE, FALSE, HTTP_BODY_MAXLENGTH, 2048], "");
}

CmdV(integer level, float t)
{
    if (level < 0) level = 0;
    if (level > 20) level = 20;
    DoGet("/sl/vibrate", "level=" + (string)level + "&time=" + (string)t);
}

CmdI(float i, float t)
{
    if (i < 0.0) i = 0.0;
    if (i > 1.0) i = 1.0;
    DoGet("/sl/intensity", "i=" + (string)i + "&time=" + (string)t);
}

CmdPreset(string name, float t)
{
    DoGet("/sl/preset", "name=" + llEscapeURL(name) + "&time=" + (string)t);
}

// Full web panel URL (clickable in dialog/chat). HUD API uses BASE only.
string PanelUrl()
{
    return TrimSlash(BASE_URL) + "/r/" + TOKEN;
}

string MenuHeader(string title)
{
    string tok = TOKEN;
    if (TokenMissing()) tok = "(not set)";
    string link = "(set BASE+TOKEN)";
    if (!TokenMissing() && !BaseUrlNeedsSetup())
        link = PanelUrl();
    // llDialog message: both link (blue) and token for the web panel
    return title + "\n" + link + "\nTOKEN: " + tok;
}

MenuMain()
{
    gPromptKind = PROMPT_NONE;
    OpenListen();
    string st = "off";
    if (gConnected) st = "on";
    llDialog(llGetOwner(), MenuHeader("Lovense [" + st + "]"),
        ["STOP", "Status", "Power", "Presets",
         "Long", "Patterns", "50%", "MAX",
         "Setup", "Help", "25%", "75%"],
        gMenuChan);
}

MenuPower()
{
    OpenListen();
    llDialog(llGetOwner(), "Power " + (string)((integer)DEFAULT_TIME) + "s",
        ["0", "5", "10", "15", "20", "30%", "60%", "«"], gMenuChan);
}

MenuPresets()
{
    OpenListen();
    llDialog(llGetOwner(), "Presets",
        ["Pulse", "Wave", "Fireworks", "Earthquake",
         "Tease", "Edge", "Heartbeat", "«"], gMenuChan);
}

MenuLong()
{
    OpenListen();
    llDialog(llGetOwner(), "Long",
        ["Slowburn", "Marathon", "Crescendo", "Afterglow",
         "Imperial", "«", "-", "-"], gMenuChan);
}

MenuPat()
{
    OpenListen();
    llDialog(llGetOwner(), "Patterns",
        ["Strobe", "Build", "Swing", "Sine", "Ramp", "Imperial", "«", "-"],
        gMenuChan);
}

MenuSetup()
{
    OpenListen();
    string tok = TOKEN;
    if (TokenMissing()) tok = "(not set)";
    llDialog(llGetOwner(), "Setup\nTOKEN:\n" + tok,
        ["Token", "URL", "Status", "Help", "«", "-", "-", "-"], gMenuChan);
}

Help()
{
    llOwnerSay("Lovense HUD | BASE=" + TrimSlash(BASE_URL));
    if (TokenMissing()) llOwnerSay("TOKEN: (not set)");
    else llOwnerSay("TOKEN: " + TOKEN);
    llOwnerSay("/" + (string)CHAT_CHANNEL + " stop|status|v 12|i 0.6|preset imperial|menu|token|url");
}

integer OnBtn(string msg)
{
    if (msg == "✖" || msg == "-" || msg == " ") return TRUE;
    if (msg == "«") { MenuMain(); return TRUE; }
    if (msg == "STOP") { DoGet("/sl/stop", ""); return TRUE; }
    if (msg == "Status") { DoGet("/sl/status", ""); return TRUE; }
    if (msg == "Power") { MenuPower(); return TRUE; }
    if (msg == "Presets") { MenuPresets(); return TRUE; }
    if (msg == "Long") { MenuLong(); return TRUE; }
    if (msg == "Patterns") { MenuPat(); return TRUE; }
    if (msg == "Setup") { MenuSetup(); return TRUE; }
    if (msg == "Token") { PromptToken(); return TRUE; }
    if (msg == "URL") { PromptUrl(); return TRUE; }
    if (msg == "Help") { Help(); return TRUE; }
    if (msg == "25%") { CmdI(0.25, DEFAULT_TIME); return TRUE; }
    if (msg == "50%") { CmdI(0.50, DEFAULT_TIME); return TRUE; }
    if (msg == "75%") { CmdI(0.75, DEFAULT_TIME); return TRUE; }
    if (msg == "30%") { CmdI(0.30, DEFAULT_TIME); return TRUE; }
    if (msg == "60%") { CmdI(0.60, DEFAULT_TIME); return TRUE; }
    if (msg == "MAX") { CmdI(1.0, DEFAULT_TIME); return TRUE; }
    if (msg == "0" || msg == "5" || msg == "10" || msg == "15" || msg == "20")
    { CmdV((integer)msg, DEFAULT_TIME); return TRUE; }
    if (msg == "Pulse") { CmdPreset("pulse", 10); return TRUE; }
    if (msg == "Wave") { CmdPreset("wave", 12); return TRUE; }
    if (msg == "Fireworks") { CmdPreset("fireworks", 10); return TRUE; }
    if (msg == "Earthquake") { CmdPreset("earthquake", 12); return TRUE; }
    if (msg == "Tease") { CmdPreset("tease", 15); return TRUE; }
    if (msg == "Edge") { CmdPreset("edge", 14); return TRUE; }
    if (msg == "Heartbeat") { CmdPreset("heartbeat", 16); return TRUE; }
    if (msg == "Slowburn") { CmdPreset("slowburn", 45); return TRUE; }
    if (msg == "Marathon") { CmdPreset("marathon", 60); return TRUE; }
    if (msg == "Crescendo") { CmdPreset("crescendo", 40); return TRUE; }
    if (msg == "Afterglow") { CmdPreset("afterglow", 35); return TRUE; }
    if (msg == "Imperial") { CmdPreset("imperial", 24); return TRUE; }
    if (msg == "Strobe")
    { DoGet("/sl/pattern", "strength=" + llEscapeURL("20;0;20;0;20;0") + "&interval=200&time=10"); return TRUE; }
    if (msg == "Build")
    { DoGet("/sl/pattern", "strength=" + llEscapeURL("4;8;12;16;20;16;12;8") + "&interval=120&time=12"); return TRUE; }
    if (msg == "Swing")
    { DoGet("/sl/pattern", "strength=" + llEscapeURL("20;15;10;5;10;15;20") + "&interval=150&time=12"); return TRUE; }
    if (msg == "Sine")
    { DoGet("/sl/pattern", "strength=" + llEscapeURL("5;10;15;20;15;10;5") + "&interval=220&time=16"); return TRUE; }
    if (msg == "Ramp")
    { DoGet("/sl/pattern", "strength=" + llEscapeURL("2;6;10;14;18;20;14;8;2") + "&interval=300&time=20"); return TRUE; }
    return FALSE;
}

OnChat(string msg)
{
    msg = llStringTrim(msg, STRING_TRIM);
    string low = llToLower(msg);
    if (OnBtn(msg)) return;
    if (low == "help" || low == "?") { Help(); return; }
    if (low == "menu") { MenuMain(); return; }
    if (low == "setup" || low == "config") { MenuSetup(); return; }
    if (low == "token") { PromptToken(); return; }
    if (low == "url" || low == "base") { PromptUrl(); return; }
    if (low == "stop" || low == "off") { DoGet("/sl/stop", ""); return; }
    if (low == "status" || low == "ping") { DoGet("/sl/status", ""); return; }
    if (llGetSubString(low, 0, 1) == "v ")
    {
        list p = llParseString2List(msg, [" "], []);
        float t = DEFAULT_TIME;
        if (llGetListLength(p) >= 3) t = (float)llList2String(p, 2);
        CmdV((integer)llList2String(p, 1), t);
        return;
    }
    if (llGetSubString(low, 0, 1) == "i ")
    {
        list p = llParseString2List(msg, [" "], []);
        float t = DEFAULT_TIME;
        if (llGetListLength(p) >= 3) t = (float)llList2String(p, 2);
        CmdI((float)llList2String(p, 1), t);
        return;
    }
    if (llGetSubString(low, 0, 6) == "preset ")
    {
        list p = llParseString2List(msg, [" "], []);
        float t = 0.0;
        if (llGetListLength(p) >= 3) t = (float)llList2String(p, 2);
        CmdPreset(llToLower(llList2String(p, 1)), t);
        return;
    }
    llOwnerSay("Unknown — help");
}

integer ReadNote()
{
    if (llGetInventoryType(NOTECARD_NAME) != INVENTORY_NOTECARD)
    {
        gNotePending = FALSE;
        return FALSE;
    }
    gNotePending = TRUE;
    gLine = 0;
    gNoteQuery = llGetNotecardLine(NOTECARD_NAME, 0);
    return TRUE;
}

CfgLine(string line)
{
    line = llStringTrim(line, STRING_TRIM);
    if (line == "" || llGetSubString(line, 0, 0) == "#") return;
    integer eq = llSubStringIndex(line, "=");
    if (eq < 1) return;
    string k = llToLower(llStringTrim(llGetSubString(line, 0, eq - 1), STRING_TRIM));
    string v = llStringTrim(llGetSubString(line, eq + 1, -1), STRING_TRIM);
    if (k == "base_url" || k == "base" || k == "url") BASE_URL = v;
    else if (k == "token") TOKEN = v;
    else if (k == "channel") CHAT_CHANNEL = (integer)v;
    else if (k == "time" || k == "default_time") DEFAULT_TIME = (float)v;
    else if (k == "hud" || k == "attach") HUD_ATTACH_POINT = (integer)v;
}

TryAttach()
{
    if (llGetAttached())
    {
        integer p = llGetAttached();
        if (p >= 31 && p <= 38)
        {
            SetupHud();
            return;
        }
        llOwnerSay("Worn but not HUD. Attach to HUD → Bottom Right.");
        return;
    }
    if (!gAttachTried)
    {
        gAttachTried = TRUE;
        llRequestPermissions(llGetOwner(), PERMISSION_ATTACH);
    }
}

default
{
    state_entry()
    {
        gConnected = FALSE;
        gLastMsg = "";
        gBusy = FALSE;
        gAttachTried = FALSE;
        gPromptKind = PROMPT_NONE;
        gNotePending = FALSE;
        gHttpCode = 0;
        gLastFaceTex = NULL_KEY;
        SetupHud();
        ReadNote();
        gListen = llListen(CHAT_CHANNEL, "", llGetOwner(), "");
        llOwnerSay("Lovense HUD ready. Touch=menu /" + (string)CHAT_CHANNEL + " help");
        TryAttach();
        if (gNotePending) llSetTimerEvent(6.0);
        else llSetTimerEvent(1.5);
    }

    on_rez(integer p) { gAttachTried = FALSE; llResetScript(); }

    attach(key id)
    {
        if (id != NULL_KEY)
        {
            SetupHud();
            if (!MaybeSetup()) DoGet("/sl/status", "");
        }
    }

    run_time_permissions(integer perm)
    {
        if (perm & PERMISSION_ATTACH)
        {
            integer point = HUD_ATTACH_POINT;
            if (point >= 1 && point <= 16)
            {
                if (point == 10) point = 38;
                else point = 38;
            }
            if (point < 31 || point > 38) point = 38;
            llAttachToAvatar(point);
        }
    }

    changed(integer change)
    {
        if (change & CHANGED_INVENTORY) ReadNote();
        if (change & CHANGED_OWNER) llResetScript();
    }

    timer()
    {
        llSetTimerEvent(0.0);
        if (!llGetAttached())
            llOwnerSay("Wear object or accept Attach (HUD).");
        if (gNotePending) return;
        if (gPromptKind != PROMPT_NONE) return;
        if (!MaybeSetup()) DoGet("/sl/status", "");
    }

    touch_start(integer n)
    {
        if (llDetectedKey(0) != llGetOwner()) return;
        if (TokenMissing()) PromptToken();
        else MenuMain();
    }

    dataserver(key id, string data)
    {
        if (id != gNoteQuery) return;
        if (data != EOF)
        {
            CfgLine(data);
            gLine += 1;
            gNoteQuery = llGetNotecardLine(NOTECARD_NAME, gLine);
        }
        else
        {
            gNotePending = FALSE;
            llListenRemove(gListen);
            gListen = llListen(CHAT_CHANNEL, "", llGetOwner(), "");
            if (!MaybeSetup()) DoGet("/sl/status", "");
        }
    }

    listen(integer channel, string name, key id, string msg)
    {
        if (id != llGetOwner()) return;
        if (channel == gMenuChan)
        {
            if (gPromptKind != PROMPT_NONE) HandlePrompt(msg);
            else OnBtn(msg);
            return;
        }
        if (channel == CHAT_CHANNEL) OnChat(msg);
    }

    http_response(key id, integer status, list meta, string body)
    {
        if (id != gReq) return;
        gBusy = FALSE;
        gHttpCode = status;
        if (status >= 200 && status < 300)
        {
            gHttpCode = 0;
            if (llSubStringIndex(body, "\"connected\":false") >= 0
                || llSubStringIndex(body, "\"connected\": false") >= 0)
                gConnected = FALSE;
            else if (llSubStringIndex(body, "\"connected\"") >= 0)
                gConnected = TRUE;
            else
                gConnected = TRUE;
            integer mi = llSubStringIndex(body, "\"message\"");
            if (mi >= 0)
            {
                integer c1 = llSubStringIndex(llGetSubString(body, mi, -1), ":");
                string rest = llGetSubString(body, mi + c1 + 1, -1);
                integer q1 = llSubStringIndex(rest, "\"");
                if (q1 >= 0)
                {
                    string r2 = llGetSubString(rest, q1 + 1, -1);
                    integer q2 = llSubStringIndex(r2, "\"");
                    if (q2 >= 0) gLastMsg = llGetSubString(r2, 0, q2 - 1);
                }
            }
            else gLastMsg = "OK";
            Look();
            if (llSubStringIndex(body, "\"connected\"") >= 0)
            {
                string pc = "no toy";
                if (gConnected) pc = "online";
                llOwnerSay("PC: " + pc + " · " + llGetSubString(gLastMsg, 0, 50));
            }
            else if (gLastMsg != "")
                llOwnerSay(llGetSubString(gLastMsg, 0, 60));
        }
        else if (status == 401)
        {
            gConnected = FALSE;
            gLastMsg = "bad token";
            Look();
            llOwnerSay("401 bad TOKEN");
            PromptToken();
        }
        else if (status == 403)
        {
            gConnected = FALSE;
            gLastMsg = "remote off";
            Look();
            llOwnerSay("403 enable remote panel on PC");
        }
        else
        {
            gConnected = FALSE;
            gLastMsg = "HTTP " + (string)status;
            Look();
            llOwnerSay("HTTP " + (string)status + " — tunnel/BASE_URL?");
        }
    }
}
