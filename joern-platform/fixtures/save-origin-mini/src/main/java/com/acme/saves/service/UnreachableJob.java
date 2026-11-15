package com.acme.saves.service;

import com.acme.saves.domain.Widget;

/** Not an endpoint, not an async root, called by nothing: outside the
 *  export's closure, so its call site is not a caller the hop counts. */
public class UnreachableJob {

    private final WidgetWriter widgetWriter;

    public UnreachableJob(WidgetWriter widgetWriter) {
        this.widgetWriter = widgetWriter;
    }

    public void run() {
        widgetWriter.storeFromTwoPlaces(new Widget("job"));
    }
}
