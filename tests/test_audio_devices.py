"""Rozpoznawanie urządzeń audio — bez odpytywania żywego PipeWire."""

from __future__ import annotations

from max2_controller.audio_react import (
    AudioApp,
    AudioEndpoint,
    apps_from_pactl_sink_inputs,
    apps_from_pw_dump,
    binary_from_desktop,
    defaults_from_pw_dump,
    endpoint_labels,
    endpoints_from_pactl_blocks,
    endpoints_from_pw_dump,
    idle_apps_from_binaries,
    match_audio_app,
)


def test_pw_dump_names_and_descriptions() -> None:
    data = [
        {
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Sink",
                    "node.name": "alsa_output.usb-Focusrite_Scarlett.analog-surround-21",
                    "node.description": "Scarlett 8i6 USB Analogowe przestrzenne 2.1",
                    "audio.channels": 3,
                }
            },
        },
        {
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Sink",
                    "node.name": "alsa_output.pci-hdmi.hdmi-stereo",
                    "node.description": "HDMI",
                    "audio.channels": "2",
                }
            },
        },
        {
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Source",
                    "node.name": "alsa_output.pci-hdmi.hdmi-stereo.monitor",
                    "node.description": "Monitor of HDMI",
                    "audio.channels": 2,
                }
            },
        },
        {
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Source",
                    "node.name": "scarlett-discord-mic",
                    "node.description": "Scarlett",
                    "audio.channels": 2,
                }
            },
        },
        {
            "type": "PipeWire:Interface:Metadata",
            "metadata": [
                {
                    "key": "default.audio.sink",
                    "value": {"name": "alsa_output.usb-Focusrite_Scarlett.analog-surround-21"},
                },
                {"key": "default.audio.source", "value": {"name": "scarlett-discord-mic"}},
            ],
        },
    ]
    sinks = endpoints_from_pw_dump(data, "sink")
    sources = endpoints_from_pw_dump(data, "source")
    assert [s.name for s in sinks] == [
        "alsa_output.usb-Focusrite_Scarlett.analog-surround-21",
        "alsa_output.pci-hdmi.hdmi-stereo",
    ]
    assert sinks[0].channels == 3
    assert sinks[0].description.startswith("Scarlett")
    # monitor głośników nie jest mikrofonem
    assert [s.name for s in sources] == ["scarlett-discord-mic"]
    ds, dsrc = defaults_from_pw_dump(data)
    assert ds.endswith("analog-surround-21")
    assert dsrc == "scarlett-discord-mic"
    labels = endpoint_labels(sinks, ds)
    assert "Scarlett 8i6 USB Analogowe przestrzenne 2.1 · domyślne" in labels
    assert "alsa_output" not in labels[0]
    mic_labels = endpoint_labels(sources, dsrc)
    assert mic_labels == ["Scarlett (scarlett-discord-mic) · domyślne"]


def test_pactl_blocks_skip_monitors() -> None:
    text = """
Sink #1
\tName: alsa_output.usb-Focusrite.analog-surround-21
\tDescription: Scarlett 8i6
\tSample Specification: s32le 3ch 48000Hz
Source #2
\tName: alsa_output.usb-Focusrite.analog-surround-21.monitor
\tDescription: Monitor of Scarlett
\tSample Specification: s32le 3ch 48000Hz
Source #3
\tName: scarlett-discord-mic
\tDescription: Scarlett
\tSample Specification: float32le 2ch 48000Hz
"""
    sinks = endpoints_from_pactl_blocks(text, "sink")
    sources = endpoints_from_pactl_blocks(text, "source")
    assert [s.name for s in sinks] == ["alsa_output.usb-Focusrite.analog-surround-21"]
    assert sinks[0].channels == 3
    assert isinstance(sinks[0], AudioEndpoint)
    assert [s.name for s in sources] == ["scarlett-discord-mic"]


def _stream(serial: int, app: str, media: str, binary: str = "game") -> dict:
    return {
        "id": serial,
        "type": "PipeWire:Interface:Node",
        "info": {
            "props": {
                "media.class": "Stream/Output/Audio",
                "application.name": app,
                "application.process.binary": binary,
                "media.name": media,
                "node.name": app,
                "object.serial": serial,
                "audio.channels": 2,
            }
        },
    }


def test_pw_dump_lists_playing_apps_not_our_tap() -> None:
    data = [
        _stream(370, "Diablo IV", "audio stream #2", "wine64-preloader"),
        _stream(371, "Firefox", "YouTube"),
        _stream(372, "Firefox", "Discord"),
        _stream(9, "Lovense Controller", "tap", "pw-record"),
        {
            "id": 80,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Stream/Input/Audio",
                    "node.name": "input.scarlett-discord-mic",
                    "object.serial": 80,
                }
            },
        },
    ]
    apps = apps_from_pw_dump(data)
    labels = [a.description for a in apps]
    assert "Diablo IV" in labels
    assert "Firefox — YouTube" in labels
    assert "Firefox — Discord" in labels
    assert all("Lovense" not in a.description for a in apps)
    diablo = next(a for a in apps if a.description == "Diablo IV")
    assert diablo.serial == 370
    assert match_audio_app(apps, diablo.name) is diablo
    again = apps_from_pw_dump([_stream(999, "Diablo IV", "audio stream #3", "wine64-preloader")])
    assert match_audio_app(again, diablo.name) is again[0]


def test_pactl_sink_inputs_parse_app() -> None:
    text = """
Sink Input #370
    application.name = "Diablo IV"
    application.process.binary = "wine64-preloader"
    media.name = "audio stream #2"
    node.name = "Diablo IV"
    object.serial = "370"
Sink Input #12
    application.name = "pw-record"
    application.process.binary = "pw-record"
    media.name = "tap"
    node.name = "lovense-audio-tap"
    object.serial = "12"
"""
    apps = apps_from_pactl_sink_inputs(text)
    assert [a.description for a in apps] == ["Diablo IV"]
    assert apps[0].serial == 370
    assert apps[0].binary == "wine64-preloader"


def test_idle_firefox_is_listed_until_it_plays() -> None:
    desktop_text = """
[Desktop Entry]
Name=Firefox
Name[pl]=Firefox
Exec=/usr/lib/firefox/firefox %u
Categories=Network;WebBrowser;
NoDisplay=false

[Desktop Action new-window]
Name=New Window
Exec=/usr/lib/firefox/firefox --new-window %u
"""
    parsed = binary_from_desktop(desktop_text)
    assert parsed is not None and parsed[:2] == ("firefox", "Firefox")
    from max2_controller.audio_react import prefer_desktop_names

    names = prefer_desktop_names(
        [
            ("steam", "Steam", 8),
            ("steam", "No Man's Sky", -5),
            ("firefox", "Firefox", 8),
        ]
    )
    assert names["steam"] == "Steam"
    assert names["firefox"] == "Firefox"
    assert binary_from_desktop("[Desktop Entry]\nName=Files\nExec=nautilus\nCategories=System;FileManager;\n") is None
    waiting = idle_apps_from_binaries({"firefox": "Firefox", "brave": "Brave"}, {"firefox", "brave"}, [])
    assert [a.description for a in waiting] == ["Brave · czeka na dźwięk", "Firefox · czeka na dźwięk"]
    live = AudioApp(
        name="Firefox\tYouTube",
        description="Firefox",
        channels=2,
        serial=50,
        binary="firefox",
    )
    only_brave = idle_apps_from_binaries(
        {"firefox": "Firefox", "brave": "Brave"}, {"firefox", "brave"}, [live]
    )
    assert [a.binary for a in only_brave] == ["brave"]
    assert match_audio_app([live, *only_brave], "proc\tfirefox") is live
    assert match_audio_app(waiting, "proc\tfirefox").serial == 0
