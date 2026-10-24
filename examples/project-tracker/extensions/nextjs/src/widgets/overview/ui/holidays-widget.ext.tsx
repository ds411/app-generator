// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual ui.dashboards.overview.widgets.holidays file
"use client";

import { t } from "@/shared/lib/i18n";
import { useResource } from "@/shared/lib/use-resource";
import { FormattedValue } from "@/shared/ui/values/formatted-value";
import { ViewLoading, ViewMessage, RetryButton } from "@/shared/ui/view-state";
import { TriangleAlertIcon } from "lucide-react";

import { nextHolidays } from "../api/next-holidays";

/** The next public holidays, from the holidays API. The server action calls the API. */
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
