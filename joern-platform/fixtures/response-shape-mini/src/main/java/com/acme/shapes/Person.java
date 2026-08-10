package com.acme.shapes;

import java.util.List;

/** Part of the §5.2.15 entity graph — see {@link Contest}. */
public class Person {

    private String id;
    private String name;
    private List<Site> sites;
    private Site primarySite;
    private List<Label> labels;
    private Label primaryLabel;
    private List<Region> regions;
    private Region primaryRegion;
    private List<Sponsor> sponsors;
    private Sponsor primarySponsor;

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public List<Site> getSites() {
        return sites;
    }

    public Site getPrimarySite() {
        return primarySite;
    }

    public List<Label> getLabels() {
        return labels;
    }

    public Label getPrimaryLabel() {
        return primaryLabel;
    }

    public List<Region> getRegions() {
        return regions;
    }

    public Region getPrimaryRegion() {
        return primaryRegion;
    }

    public List<Sponsor> getSponsors() {
        return sponsors;
    }

    public Sponsor getPrimarySponsor() {
        return primarySponsor;
    }
}
