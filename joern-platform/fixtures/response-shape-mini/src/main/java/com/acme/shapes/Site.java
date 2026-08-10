package com.acme.shapes;

import java.util.List;

/** Part of the §5.2.15 entity graph — see {@link Contest}. */
public class Site {

    private String id;
    private String name;
    private List<Label> labels;
    private Label primaryLabel;
    private List<Region> regions;
    private Region primaryRegion;
    private List<Sponsor> sponsors;
    private Sponsor primarySponsor;
    private List<Award> awards;
    private Award primaryAward;

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
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

    public List<Award> getAwards() {
        return awards;
    }

    public Award getPrimaryAward() {
        return primaryAward;
    }
}
