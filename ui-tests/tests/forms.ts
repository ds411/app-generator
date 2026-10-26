// The forms in a sheet. Under load (for example with the checks of the
// pre-push hook in parallel), a click on "Save" can come before the form
// is ready and save nothing, so the helper clicks again while the sheet is
// open.
import { expect, type Locator } from "@playwright/test";

/**
 * Click "Save" in a sheet, and wait until the sheet closes. A second save
 * of the same values gives the same record, and the same count of lines.
 */
export async function saveAndClose(sheet: Locator): Promise<void> {
  await expect(async () => {
    if (await sheet.isVisible()) {
      await sheet.getByRole("button", { name: "Save", exact: true }).click({ timeout: 2_000 });
    }
    await expect(sheet).toBeHidden({ timeout: 3_000 });
  }).toPass({ timeout: 30_000 });
}
