// Lovense JAR HOST — rez/kill the floor vessel, relay its chat to the controller.
// Third script in the Glass ROOT. No HTTP. No look. No vibe menu.

string JAR_OBJECT = "LovenseTipJar";

integer gMenuChan;
integer gMenuListen;
integer gCmdListen;
integer gHasJar;

integer CmdChan()
{
    return 0xC07E1000 ^ (integer)("0x" + llGetSubString((string)llGetOwner(), 0, 7));
}

Relay(string s, key id)
{
    llMessageLinked(LINK_SET, 0xC07E, s, id);
}

string FindJarObject()
{
    if (llGetInventoryType(JAR_OBJECT) == INVENTORY_OBJECT)
        return JAR_OBJECT;
    integer i;
    integer n = llGetInventoryNumber(INVENTORY_OBJECT);
    for (i = 0; i < n; i += 1)
    {
        string nm = llGetInventoryName(INVENTORY_OBJECT, i);
        string lo = llToLower(nm);
        if (llSubStringIndex(lo, "tipjar") >= 0) return nm;
        if (llSubStringIndex(lo, "tip jar") >= 0) return nm;
    }
    return "";
}

vector JarFeetPos()
{
    key who = llGetOwner();
    list det = llGetObjectDetails(who, [OBJECT_POS, OBJECT_ROT]);
    vector av = llList2Vector(det, 0);
    rotation avr = llList2Rot(det, 1);
    vector sz = llGetAgentSize(who);
    vector here = llGetPos();
    rotation face = llGetRot();
    vector pos;
    if (sz.z > 0.1)
    {
        pos = av + (llRot2Fwd(avr) * 0.55);
        pos.z = av.z - (sz.z * 0.5) + 0.05;
    }
    else
    {
        pos = here + (llRot2Fwd(face) * 0.6);
        pos.z = here.z;
    }
    if (llVecDist(pos, here) > 9.4)
    {
        pos = here + (llRot2Fwd(avr) * 0.4);
        pos.z = here.z - 1.6;
    }
    return pos;
}

RezJar()
{
    string nm = FindJarObject();
    if (nm == "")
    {
        llOwnerSay("No tip jar in this orb. Put a COPY named LovenseTipJar in Glass Contents.");
        return;
    }
    integer mask = llGetInventoryPermMask(nm, MASK_OWNER);
    if (!(mask & PERM_COPY))
        llOwnerSay("Jar is no-copy — it will leave the orb.");
    llRegionSay(CmdChan(), "TJ|die");
    llRezAtRoot(nm, JarFeetPos(), ZERO_VECTOR, ZERO_ROTATION, 0xC07E);
    llOwnerSay("Rezzing tip jar at your feet.");
}

OpenMenu()
{
    gMenuChan = 0x80000000 | (integer)llFrand(0x7FFFFFFF);
    llListenRemove(gMenuListen);
    gMenuListen = llListen(gMenuChan, "", llGetOwner(), "");
    string heard = "no vessel";
    if (gHasJar) heard = "vessel ok";
    llDialog(llGetOwner(),
        "Floor tip jar [" + heard + "]\nRez jar drops the vessel at your feet.",
        ["Rez jar", "Kill jar", "Jar open", "Jar close",
         "Reset $", "Test 50", "-", "-"],
        gMenuChan);
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
        gHasJar = FALSE;
        llListenRemove(gCmdListen);
        gCmdListen = llListen(CmdChan(), "", NULL_KEY, "");
        llOwnerSay("Jar host ready. Orb menu → Rez jar.");
    }

    object_rez(key id)
    {
        gHasJar = TRUE;
        llOwnerSay("Tip jar is on the ground. Left click = Pay.");
    }

    link_message(integer sender, integer num, string str, key id)
    {
        if (num != 0xC07E) return;
        if (str == "JAR|rez") { RezJar(); return; }
        if (str == "JAR|menu") { OpenMenu(); return; }
        if (str == "JAR|kill")
        {
            llRegionSay(CmdChan(), "TJ|die");
            gHasJar = FALSE;
            return;
        }
        if (str == "JAR|reset")
        {
            llRegionSay(CmdChan(), "TJ|reset");
            return;
        }
    }

    listen(integer channel, string name, key id, string msg)
    {
        if (channel == CmdChan())
        {
            if (llGetAgentSize(id) != ZERO_VECTOR) return;
            if (llGetOwnerKey(id) != llGetOwner()) return;
            if (msg == "TJ|hello" || msg == "TJ|ping")
            {
                gHasJar = TRUE;
                llRegionSayTo(id, CmdChan(), "TJ|pong");
                return;
            }
            if (llGetSubString(msg, 0, 6) == "TIPTXT|")
            {
                Relay(msg, id);
                return;
            }
            if (llGetSubString(msg, 0, 7) == "TJ|buzz|")
            {
                Relay(msg, id);
                return;
            }
            if (llGetSubString(msg, 0, 3) == "LVQ|")
            {
                Relay(msg, id);
                return;
            }
            return;
        }
        if (channel != gMenuChan) return;
        if (id != llGetOwner()) return;
        if (msg == "-" || msg == " ") return;
        if (msg == "Rez jar") { RezJar(); return; }
        if (msg == "Kill jar")
        {
            llRegionSay(CmdChan(), "TJ|die");
            gHasJar = FALSE;
            llOwnerSay("Told the floor jar to die.");
            return;
        }
        if (msg == "Jar open")
        {
            llRegionSay(CmdChan(), "TJ|open");
            llOwnerSay("Told the floor jar: open.");
            return;
        }
        if (msg == "Jar close")
        {
            llRegionSay(CmdChan(), "TJ|close");
            llOwnerSay("Told the floor jar: close.");
            return;
        }
        if (msg == "Reset $")
        {
            llRegionSay(CmdChan(), "TJ|reset");
            return;
        }
        if (msg == "Test 50")
        {
            llRegionSay(CmdChan(), "TJ|test50");
            return;
        }
    }
}
