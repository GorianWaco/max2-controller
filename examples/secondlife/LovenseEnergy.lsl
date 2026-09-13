// Lovense ENERGY — charge bank + hover color.
// Extra script in Glass ROOT. No HTTP.

integer gMenuChan;
integer gMenuListen;
integer gPrompt;
integer gBankN;
string  gBankQ;
integer gEnergy;
vector  TEXT_COLOR;

ParseColor(string s)
{
    s = llStringTrim(s, STRING_TRIM);
    list p = llParseString2List(s, [" ", ",", ";"], []);
    if (llGetListLength(p) < 3) return;
    float r = (float)llList2String(p, 0);
    float g = (float)llList2String(p, 1);
    float b = (float)llList2String(p, 2);
    if (r > 1.0 || g > 1.0 || b > 1.0)
    {
        r = r / 255.0;
        g = g / 255.0;
        b = b / 255.0;
    }
    TEXT_COLOR = <r, g, b>;
}

Save()
{
    llLinksetDataWrite("lv.color",
        (string)TEXT_COLOR.x + " " + (string)TEXT_COLOR.y + " " + (string)TEXT_COLOR.z);
    llLinksetDataWrite("lv.bank", gBankQ);
    llLinksetDataWrite("lv.bankn", (string)gBankN);
    llLinksetDataWrite("lv.energy", (string)gEnergy);
}

Load()
{
    TEXT_COLOR = <1.00, 0.82, 0.90>;
    string col = llLinksetDataRead("lv.color");
    if (col != "") ParseColor(col);
    gBankQ = llLinksetDataRead("lv.bank");
    gBankN = (integer)llLinksetDataRead("lv.bankn");
    gEnergy = (integer)llLinksetDataRead("lv.energy");
    if (gBankN < 1 && gBankQ != "") gBankN = 1;
    if (gEnergy < 1 && gBankN > 0)
    {
        gEnergy = gBankN * 8;
        if (gEnergy > 100) gEnergy = 100;
    }
}

Bar(integer e)
{
    integer n = (e + 5) / 10;
    if (n < 0) n = 0;
    if (n > 10) n = 10;
    string s;
    integer i;
    for (i = 0; i < 10; i += 1)
    {
        if (i < n) s += "●";
        else s += "○";
    }
    if (e < 1 && gBankN < 1)
    {
        llMessageLinked(LINK_SET, 0xC07E, "ENERTXT|", NULL_KEY);
        return;
    }
    string line = "Energy  " + s + "  " + (string)e;
    if (gBankN > 0) line += "  x" + (string)gBankN;
    llMessageLinked(LINK_SET, 0xC07E, "ENERTXT|" + line, NULL_KEY);
}

BankAdd(string pend)
{
    if (pend == "" || pend == "stop" || pend == "replay" || pend == "clearbank")
        return;
    if (gBankN >= 24)
    {
        integer c = llSubStringIndex(gBankQ, "^");
        if (c >= 0) gBankQ = llGetSubString(gBankQ, c + 1, -1);
        else gBankQ = "";
        if (gBankN > 0) gBankN -= 1;
    }
    if (gBankQ != "") gBankQ += "^";
    gBankQ += pend;
    gBankN += 1;
    gEnergy = gBankN * 8;
    if (gEnergy > 100) gEnergy = 100;
    Save();
    Bar(gEnergy);
    llOwnerSay("stored energy " + (string)gEnergy + "%  x" + (string)gBankN);
}

Flush()
{
    gBankQ = "";
    gBankN = 0;
    llLinksetDataWrite("lv.bank", "");
    llLinksetDataWrite("lv.bankn", "0");
}

ClearAll()
{
    Flush();
    gEnergy = 0;
    llLinksetDataWrite("lv.energy", "0");
    llMessageLinked(LINK_SET, 0xC07E, "ENERTXT|", NULL_KEY);
    llOwnerSay("Energy queue cleared.");
}

OpenColor()
{
    gPrompt = 0;
    gMenuChan = 0x80000000 | (integer)llFrand(0x7FFFFFFF);
    llListenRemove(gMenuListen);
    gMenuListen = llListen(gMenuChan, "", llGetOwner(), "");
    llDialog(llGetOwner(), "Hover text color",
        ["Pink", "Cyan", "Gold", "White",
         "Green", "Red", "Blue", "Lilac",
         "Custom", "-", "-", "-"],
        gMenuChan);
}

SetCol(vector c)
{
    TEXT_COLOR = c;
    Save();
    llMessageLinked(LINK_SET, 0xC07E, "EN|repaint", NULL_KEY);
}

default
{
    state_entry()
    {
        if (llGetLinkNumber() > 1)
        {
            llRemoveInventory(llGetScriptName());
            return;
        }
        gPrompt = 0;
        Load();
        Bar(gEnergy);
        llOwnerSay("Energy: offline clicks charge the bar. Setup → Color / Stats → Replay.");
    }

    link_message(integer sender, integer num, string str, key id)
    {
        if (num != 0xC07E) return;
        if (llGetSubString(str, 0, 6) == "EN|add|")
        {
            BankAdd(llGetSubString(str, 7, -1));
            return;
        }
        if (str == "EN|color") { OpenColor(); return; }
        if (str == "EN|clear") { ClearAll(); return; }
        if (str == "EN|flush") { Flush(); return; }
        if (llGetSubString(str, 0, 6) == "EN|set|")
        {
            ParseColor(llGetSubString(str, 7, -1));
            Save();
            llMessageLinked(LINK_SET, 0xC07E, "EN|repaint", NULL_KEY);
            return;
        }
        if (llGetSubString(str, 0, 5) == "EN|pc|")
        {
            list p = llParseString2List(str, ["|"], []);
            gEnergy = (integer)llList2String(p, 2);
            gBankN = (integer)llList2String(p, 3);
            llLinksetDataWrite("lv.energy", (string)gEnergy);
            llLinksetDataWrite("lv.bankn", (string)gBankN);
            Bar(gEnergy);
            return;
        }
    }

    listen(integer channel, string name, key id, string msg)
    {
        if (channel != gMenuChan) return;
        if (id != llGetOwner()) return;
        if (gPrompt == 1)
        {
            gPrompt = 0;
            ParseColor(msg);
            Save();
            llMessageLinked(LINK_SET, 0xC07E, "EN|repaint", NULL_KEY);
            llOwnerSay("Hover color saved.");
            return;
        }
        if (msg == "-" || msg == " ") return;
        if (msg == "Pink") SetCol(<0.95, 0.55, 0.72>);
        else if (msg == "Cyan") SetCol(<0.35, 0.85, 0.95>);
        else if (msg == "Gold") SetCol(<1.00, 0.82, 0.40>);
        else if (msg == "White") SetCol(<1.00, 1.00, 1.00>);
        else if (msg == "Green") SetCol(<0.55, 0.95, 0.60>);
        else if (msg == "Red") SetCol(<1.00, 0.40, 0.40>);
        else if (msg == "Blue") SetCol(<0.45, 0.60, 1.00>);
        else if (msg == "Lilac") SetCol(<0.82, 0.70, 1.00>);
        else if (msg == "Custom")
        {
            gPrompt = 1;
            llTextBox(llGetOwner(), "Hover color: r g b  (0-1 or 0-255)", gMenuChan);
        }
    }
}
