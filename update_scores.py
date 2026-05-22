import asyncio
from sqlalchemy import select
from main import async_session, Lead, OrganizationConfig, evaluate_lead

async def update_all_scores():
    async with async_session() as session:
        # Načítaj konfiguráciu pre org_id=1
        result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == 1))
        org_config = result.scalar_one_or_none()
        if not org_config:
            print("Konfigurácia neexistuje")
            return

        # Načítaj všetkých leadov
        result = await session.execute(select(Lead))
        leads = result.scalars().all()
        print(f"Načítaných {len(leads)} leadov")

        for lead in leads:
            # Rule-based skóre
            rule_score = evaluate_lead(lead.lead_metadata or {}, org_config.scoring_rules)
            # Ak má ai_adjustment, použije sa, inak 0
            adjustment = lead.ai_adjustment if lead.ai_adjustment is not None else 0
            final_score = rule_score + adjustment
            final_score = max(0, min(100, final_score))
            # Tier
            thresholds = org_config.tier_thresholds
            if final_score >= thresholds["HOT"]:
                tier = "HOT"
            elif final_score >= thresholds["WARM"]:
                tier = "WARM"
            elif final_score >= thresholds["COOL"]:
                tier = "COOL"
            else:
                tier = "DEAD"
            # Aktualizuj leada
            lead.rule_score = rule_score
            lead.final_score = final_score
            lead.tier = tier
            print(f"Lead {lead.primary_identifier}: rule={rule_score}, final={final_score}, tier={tier}")

        await session.commit()
        print("Hotovo – skóre boli aktualizované.")

asyncio.run(update_all_scores())