// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual ui.dashboards.overview.widgets.holidays file
import { holidaysClient, type PublicHoliday } from "@/shared/api/holidays";
import { t } from "@/shared/lib/i18n";
import { useResource } from "@/shared/lib/use-resource";
import { FormattedValue } from "@/shared/ui/values/formatted-value";
import { ViewLoading, ViewMessage, RetryButton } from "@/shared/ui/view-state";
import { TriangleAlertIcon } from "lucide-react";

/** The country of the public holidays of the dashboard. */
const COUNTRY_CODE = "DE";

// @trace:manual apis.holidays.operations.getNextPublicHolidays
/** Return the public holidays of the next 365 days that are in all regions of the country. */
async function nextHolidays(): Promise<PublicHoliday[]> {
  const holidays = await holidaysClient().getNextPublicHolidays({ countryCode: COUNTRY_CODE });
  return holidays.filter((holiday) => holiday.global);
}

/**
 * The next public holidays, from the holidays API. The browser calls the
 * API. With mock data, the client gives the examples of the OpenAPI document.
 */
export function HolidaysWidget() {
  const resource = useResource("next-holidays", nextHolidays);
  if (resource.status === "loading") {
    return <ViewLoading indicator="skeleton" shape="widget" />;
  }
  if (resource.status === "error") {
    return (
      <ViewMessage
        tone="error"
        title={t("Something went wrong")}
        text={t("Try again in a moment.")}
        icon={TriangleAlertIcon}
        action={<RetryButton onRetry={resource.reload} />}
      />
    );
  }
  if (resource.data.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">{t("Nothing here yet")}</p>;
  }
  return (
    <ul className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
      {resource.data.slice(0, 6).map((holiday) => (
        <li key={holiday.date} className="flex items-baseline justify-between gap-4 border-b py-2 text-sm">
          <span className="font-medium">{holiday.name}</span>
          <FormattedValue value={holiday.date} format="date" className="text-muted-foreground" />
        </li>
      ))}
    </ul>
  );
}
