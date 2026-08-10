package com.acme.shapes;

import java.util.List;

/** Part of the §5.2.15 entity graph — see {@link Contest}. */
public class Label {

    private String id;
    private String name;
    private List<Region> regions;
    private Region primaryRegion;
    private List<Sponsor> sponsors;
    private Sponsor primarySponsor;
    private List<Award> awards;
    private Award primaryAward;
    private List<Contest> contests;
    private Contest primaryContest;

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
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

    public List<Contest> getContests() {
        return contests;
    }

    public Contest getPrimaryContest() {
        return primaryContest;
    }
}
