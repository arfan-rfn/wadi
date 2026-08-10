package com.acme.shapes;

import java.util.List;

/** Part of the §5.2.15 entity graph — see {@link Contest}. */
public class Region {

    private String id;
    private String name;
    private List<Sponsor> sponsors;
    private Sponsor primarySponsor;
    private List<Award> awards;
    private Award primaryAward;
    private List<Contest> contests;
    private Contest primaryContest;
    private List<Team> teams;
    private Team primaryTeam;

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
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

    public List<Team> getTeams() {
        return teams;
    }

    public Team getPrimaryTeam() {
        return primaryTeam;
    }
}
