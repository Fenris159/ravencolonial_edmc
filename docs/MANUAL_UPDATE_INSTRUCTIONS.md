# Manual update (when auto-update does not work)

The plugin can update itself from the in-app settings when auto-update is enabled and GitHub is reachable. Use these steps **only as a fallback**—for example if auto-update fails, you prefer to install by hand, or you are troubleshooting.

**Latest release (download and release notes):**  
[https://github.com/Fenris159/ravencolonial_edmc/releases](https://github.com/Fenris159/ravencolonial_edmc/releases)

Open the **latest** release, download the **plugin ZIP** asset (not the source archive unless the release page says otherwise), then follow your platform below.

---

## Windows

1. Download the plugin ZIP from the [releases](https://github.com/Fenris159/ravencolonial_edmc/releases) page.
2. Close EDMarketConnector if it is running.
3. Go to: `%LOCALAPPDATA%\EDMarketConnector\plugins\`
4. Delete the existing `RavenColonial_EDMC` folder.
5. Extract the ZIP.
6. Place the `RavenColonial_EDMC` folder from the archive into the `plugins` folder (so you have `plugins\RavenColonial_EDMC\` with the plugin files inside).
7. Start EDMarketConnector again.

---

## Linux

1. Download the plugin ZIP from the [releases](https://github.com/Fenris159/ravencolonial_edmc/releases) page.
2. Close EDMarketConnector if it is running.
3. Remove the old plugin folder, for example:

   ```bash
   rm -rf ~/.local/share/EDMarketConnector/plugins/RavenColonial_EDMC
   ```

4. Extract the ZIP into the plugins directory (use the path where you saved the file):

   ```bash
   cd ~/.local/share/EDMarketConnector/plugins/
   unzip /path/to/the-plugin-archive-you-downloaded.zip
   ```

5. Confirm a `RavenColonial_EDMC` folder exists under `plugins` with the plugin contents.
6. Start EDMarketConnector again.

---

## macOS

1. Download the plugin ZIP from the [releases](https://github.com/Fenris159/ravencolonial_edmc/releases) page.
2. Close EDMarketConnector if it is running.
3. Go to: `~/Library/Application Support/EDMarketConnector/plugins/`
4. Delete the existing `RavenColonial_EDMC` folder.
5. Extract the ZIP and move the `RavenColonial_EDMC` folder into `plugins`.
6. Start EDMarketConnector again.

---

## After installing

In EDMarketConnector, open **File → Settings** and select the Ravencolonial plugin tab. The version line at the bottom should match what you expect from the release you installed. You can turn auto-update back on for future releases if you use that feature.

If something still fails, check the EDMarketConnector log and the release notes on GitHub for that version.
