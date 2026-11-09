// Without native plugins: the browser and Android cannot load DLL/SO plugins, and their ABI is x86-64
// "win64" (macOS and ARM64 have none yet). Built-in effects and codecs still register through their
// ordinary library entrypoints and keep their ordering.

use jflib::{img_all, ui};

use crate::app::Pn;
use crate::app::constants::*;
use crate::app::commands::pn_cmd_set;
use alloc::string::String;
use ui::*;

#[derive(Default)]
pub(crate) struct Plug;

pub(crate) fn plug_init(_p: &mut Pn, _ui: &mut Ui) {
    jflib::fx::use_all();
    img_all::use_all_codecs();
}
pub(crate) fn plug_states(_p: &mut Pn, ui: &mut Ui) {
    // the browser shows the row greyed; elsewhere it stays hidden, as the native host's without errors
    pn_cmd_set(ui, CMD_FX_PLUGIN_ERRORS, if cfg!(target_arch = "wasm32") { CF_DISABLED } else { CF_HIDDEN });
}
pub(crate) fn plug_frame(_p: &mut Pn, ui: &mut Ui) {
    ui.last_reset();
    ui.sem(
        K_TEXT,
        ID_PLUG_FIRST,
        Some(if cfg!(target_arch = "wasm32") {
            "Native DLL-/SO-Plugins sind im Browser nicht verfügbar."
        } else {
            "Native Plugins gibt es für dieses System noch nicht."
        }),
        0,
    );
}
pub(crate) fn plug_cmd(p: &mut Pn, ui: &mut Ui, id: u32, arg: u32) -> bool {
    if id == CMD_FX_PLUGIN_ERRORS {
        crate::workspace::dialogs::settings::set_cmd(p, ui, CMD_SET_PAGE, SP_PLUGINS as u32);
        return true;
    }
    if (CMD_P1_FIRST..=CMD_P1_LAST).contains(&id) {
        return false;
    }
    // Statically registered library effects can use dynamically populated menu rows.
    crate::effects::fx_cmd(p, ui, id, arg)
}
pub(crate) fn plug_shapes_feed(_p: &mut Pn) {}
pub(crate) fn plug_count(_p: &Plug) -> i32 {
    0
}
pub(crate) fn plug_errors(_p: &Plug) -> i32 {
    0
}
pub(crate) fn plug_loaded(_p: &Plug) -> i32 {
    0
}
pub(crate) fn plug_text(_p: &Plug, _index: i32) -> (u32, String) {
    (0, String::new())
}
