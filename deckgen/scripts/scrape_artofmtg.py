import json
import re
import time
from bs4 import BeautifulSoup
import requests

# HTML con la lista de sets que proporcionaste
SETS_HTML = """
<p><a title="Secret Lair MtG Art" href="https://www.artofmtg.com/mtg-set/secret-lair/">Secret Lair</a> | <a title="Promos Art" href="https://www.artofmtg.com/fnm-promo-cards/">PROMOS</a></p>
<h2>2024</h2>
<p><a title="Foundations MtG Art" href="https://www.artofmtg.com/mtg-set/foundations/">Foundations</a> | <a href="https://www.artofmtg.com/mtg-set/bloomburrow/">Bloomburrow</a> | Duskmourn | Assassin’s Creed | Modern Horizons III | Outlaws of Thunder Junction | Fallout | <a href="https://www.artofmtg.com/mtg-set/murders-at-karlov-manor/">Murders at Karlov Manor</a></p>
<h2>2023</h2>
<p><a href="https://www.artofmtg.com/mtg-set/the-lost-caverns-of-ixalan/">The Lost Caverns of Ixalan</a> | <a href="https://www.artofmtg.com/mtg-set/wilds-of-eldraine/">Wilds of Eldraine</a> | <a href="https://www.artofmtg.com/mtg-set/march-of-the-machine/">March of the Machine</a> | <a title="Phyrexia: All Will Be One MtG Art" href="https://www.artofmtg.com/mtg-set/phyrexia-all-will-be-one/">Phyrexia: All Will Be One</a></p>
<h2>2022</h2>
<p><a title="Jumpstart 2022 MtG Art" href="https://www.artofmtg.com/mtg-set/jumpstart-2022/">Jumpstart 2022</a> | <a title="The Brothers' War MtG Art" href="https://www.artofmtg.com/mtg-set/the-brothers-war/">The Brothers’ War</a> | <a title="Unfinity MtG Art" href="https://www.artofmtg.com/mtg-set/unfinity/">Unfinity</a> | <a title="Dominaria United MtG Art" href="https://www.artofmtg.com/mtg-set/dominaria-united/">Dominaria United</a> | <a title="Warhammer 40.000 MtG Art" href="https://www.artofmtg.com/mtg-set/warhammer-40000/">Warhammer 40.000</a> | <a title="Double Masters 2022 MtG Art" href="https://www.artofmtg.com/mtg-set/double-masters-2022/">Double Masters 2022</a> | <a title="Commander Legends: Battle for Baldur's Gate MtG Art" href="https://www.artofmtg.com/mtg-set/commander-legends-battle-for-baldurs-gate/">Commander Legends: Battle for Baldur’s Gate</a> | <a title="Streets of New Capenna MtG Art" href="https://www.artofmtg.com/mtg-set/streets-of-new-capenna/">Streets of New Capenna</a> | <a title="Kamigawa: Neon Dynasty MtG Art" href="https://www.artofmtg.com/mtg-set/kamigawa-neon-dynasty/">Kamigawa: Neon Dynasty</a></p>
<h2>2021</h2>
<p><a title="Alchemy: Innistrad MtG Art" href="https://www.artofmtg.com/mtg-set/alchemy-innistrad/">Alchemy: Innistrad</a> | <a title="Innistrad: Crimson Vow Art" href="https://www.artofmtg.com/mtg-set/innistrad-crimson-vow/">Innistrad: Crimson Vow</a> | <a title="Innistrad: Midnight Hunt Art" href="https://www.artofmtg.com/mtg-set/innistrad-midnight-hunt/">Innistrad: Midnight Hunt</a> | <a title="Adventures in the Forgotten Realms Art" href="https://www.artofmtg.com/mtg-set/adventures-in-the-forgotten-realms/">Adventures in the Forgotten Realms</a> | <a title="Modern Horizons 2 MtG Art" href="https://www.artofmtg.com/mtg-set/modern-horizons-2/">Modern Horizons 2</a> | <a title="Strixhaven MtG Art" href="https://www.artofmtg.com/mtg-set/strixhaven/">Strixhaven</a> | <a title="Strixhaven MtG Art" href="https://www.artofmtg.com/mtg-set/commander-2021/">Commander 2021</a> | <a title="Time Spiral Remastered MtG Art" href="https://www.artofmtg.com/mtg-set/time-spiral-remastered/">Time Spiral Remastered</a> | <a title="Kaldheim Art" href="https://www.artofmtg.com/mtg-set/kaldheim/">Kaldheim</a></p>
<h2>2020</h2>
<p><a title="Zendikar Rising Art" href="https://www.artofmtg.com/mtg-set/zendikar-rising/">Zendikar Rising</a> | <a title="Core Set 2021 MtG Art" href="https://www.artofmtg.com/mtg-set/core-set-2021/">Core Set 2021</a> | <a title="Commander 2020 Art" href="https://www.artofmtg.com/mtg-set/commander-2020/">Commander 2020</a> | <a title="Ikoria Art" href="https://www.artofmtg.com/mtg-set/ikoria/">Ikoria: Lair of Behemoths</a> | <a title="Theros Beyond Death Art" href="https://www.artofmtg.com/mtg-set/theros-beyond-death/">Theros Beyond Death</a> | <a title="Commander Collection: Green MtG Art" href="https://www.artofmtg.com/mtg-set/commander-collection-green/">Commander Collection: Green</a> | <a title="Commander Legends Art" href="https://www.artofmtg.com/mtg-set/commander-legends/">Commander Legends</a> | <a title="Double Masters MtG Art" href="https://www.artofmtg.com/mtg-set/double-masters/">Double Masters</a> | <a title="Jumpstart Art" href="https://www.artofmtg.com/mtg-set/jumpstart/">Jumpstart</a></p>
<h2>2019</h2>
<p><a title="Throne of Eldraine MtG Art" href="https://www.artofmtg.com/mtg-set/throne-of-eldraine/">Throne of Eldraine</a> | <a title="Commander 2019 MtG Art" href="https://www.artofmtg.com/mtg-set/commander-2019/">Commander 2019</a> | <a title="Core Set 2020 MtG Art" href="https://www.artofmtg.com/mtg-set/core-set-2020/">Core Set 2020</a> | <a title="Signature Spellbook: Gideon MtG Art" href="https://www.artofmtg.com/mtg-set/signature-spellbook-gideon/">Signature Spellbook: Gideon</a> | <a title="Modern Horizons MtG Art" href="https://www.artofmtg.com/mtg-set/modern-horizons/">Modern Horizons</a> | <a title="War of the Spark MtG Art" href="https://www.artofmtg.com/mtg-set/war-of-the-spark/">War of the Spark</a> | <a title="Ravnica Allegiance MtG Art" href="https://www.artofmtg.com/mtg-set/ravnica-allegiance/">Ravnica Allegiance</a></p>
<h2>2018</h2>
<p><a title="Ultimate Masters Mtg Art" href="https://www.artofmtg.com/mtg-set/ultimate-masters/">Ultimate Masters</a> | <a title="Guilds of Ravnica MtG Art" href="https://www.artofmtg.com/mtg-set/guilds-of-ravnica/">Guilds of Ravnica</a> | <a title="Commander 2018 Art" href="https://www.artofmtg.com/mtg-set/commander-2018/">Commander 2018</a> | <a title="Core Set 2019 MtG Art" href="https://www.artofmtg.com/core-set-2019/">Core Set 2019</a> | <a title="Signature Spellbook: Jace MtG Art" href="https://www.artofmtg.com/mtg-set/signature-spellbook-jace/">Signature Spellbook: Jace</a> | <a title="Battlebond Art" href="https://www.artofmtg.com/mtg-set/battlebond/">Battlebond</a> | <a title="Dominaria MtG Art" href="https://www.artofmtg.com/mtg-set/dominaria/">Dominaria</a> | <a title="Masters 25 MtG Art" href="https://www.artofmtg.com/mtg-set/masters-25/">Masters 25</a> | <a title="Rivals of Ixalan MTG Art" href="https://www.artofmtg.com/mtg-set/rivals-of-ixalan/">Rivals of Ixalan</a> | <a title="Duel Decks: Elves vs. Inventors MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-elves-vs-inventors/">Duel Decks: Elves vs. Inventors</a></p>
<h2>2017</h2>
<p><a title="Unstable MtG Art" href="https://www.artofmtg.com/mtg-set/unstable/">Unstable</a> | <a title="From the Vault: Transform MtG Art" href="https://www.artofmtg.com/mtg-set/from-the-vault-transform/">From the Vault: Transform</a> | <a title="Explorers of Ixalan MtG Art" href="https://www.artofmtg.com/mtg-set/explorers-of-ixalan/">Explorers of Ixalan</a> | <a title="Iconic Masters MtG Art" href="https://www.artofmtg.com/mtg-set/iconic-masters/">Iconic Masters</a> | <a title="Duel Decks: Merfolk vs. Goblins MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-merfolk-vs-goblins/">Duel Decks: Merfolk vs. Goblins</a> | <a title="Ixalan MtG Art" href="https://www.artofmtg.com/mtg-set/ixalan/">Ixalan</a> | <a title="Commander 2017" href="https://www.artofmtg.com/mtg-set/commander-2017/">Commander 2017</a> | <a title="Hour of Devastation MtG Art" href="https://www.artofmtg.com/mtg-set/hour-of-devastation/">Hour of Devastation</a> | <a title="Amonkhet Art" href="https://www.artofmtg.com/mtg-set/amonkhet/">Amonkhet</a> | <a title="Duel Decks: Mind vs. Might MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-mind-vs-might/">Duel Decks: Mind vs. Might</a> | <a title="Modern Masters 2017 MtG Art" href="https://www.artofmtg.com/mtg-set/modern-masters-2017/">Modern Masters 2017</a> | <a title="Aether Revolt Art" href="https://www.artofmtg.com/mtg-set/aether-revolt/">Aether Revolt</a></p>
<h2>2016</h2>
<p><a title="Commander 2016 Art" href="https://www.artofmtg.com/mtg-set/commander-2016/">Commander 2016</a> | <a title="Kaladesh MTG Art" href="https://www.artofmtg.com/mtg-set/kaladesh/">Kaladesh</a> | <a title="Conspiracy: Take the Crown MTG Art" href="https://www.artofmtg.com/mtg-set/conspiracy-take-the-crown/">Conspiracy: Take the Crown</a> | <a title="From the Vault: Lore MtG Art" href="https://www.artofmtg.com/mtg-set/from-the-vault-lore/">From the Vault: Lore</a> | <a title="Eldritch Moon MTG Art" href="https://www.artofmtg.com/mtg-set/eldritch-moon/">Eldritch Moon</a> | <a title="Eternal Masters MtG Art" href="https://www.artofmtg.com/mtg-set/eternal-masters/">Eternal Masters</a> | <a title="Shadows over Innistrad MtG Art" href="https://www.artofmtg.com/mtg-set/shadows-over-innistrad/">Shadows Over Innistrad</a> | <a title="Duel Decks: Blessed vs. Cursed MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-blessed-vs-cursed/">Duel Decks: Blessed vs. Cursed</a> | <a title="Oath of the Gatewatch MTG Art" href="https://www.artofmtg.com/mtg-set/oath-of-the-gatewatch/">Oath of the Gatewatch</a> | <a title="Duel Decks: Nissa vs. Ob Nixilis MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-nissa-vs-ob-nixilis/">Duel Decks: Nissa vs. Ob Nixilis</a></p>
<h2>2015</h2>
<p><a title="Commander 2015 Art" href="https://www.artofmtg.com/mtg-set/commander-2015/">Commander 2015</a> | <a title="Battle for Zendikar Art" href="https://www.artofmtg.com/mtg-set/battle-for-zendikar/">Battle for Zendikar</a> | Duel Decks: Zendikar vs. Eldrazi | <a title="Magic Origins MtG Art" href="https://www.artofmtg.com/mtg-set/origins/">Magic Origins</a> | <a title="Modern Masters 2015 MtG Art" href="https://www.artofmtg.com/mtg-set/modern-masters-2015/">Modern Masters 2015</a> | <a title="Dragons of Tarkir MtG Art" href="https://www.artofmtg.com/mtg-set/dragons-of-tarkir/">Dragons of Tarkir</a> | <a title="Elspeth vs. Kiora MtG Art" href="https://www.artofmtg.com/mtg-set/elspeth-vs-kiora/">Duel Decks: Elspeth vs. Kiora</a> | <a title="Fate Reforged MtG Art" href="https://www.artofmtg.com/mtg-set/fate-reforged/">Fate Reforged</a></p>
<h2>2014</h2>
<p><a title="Commander 2014 Art" href="https://www.artofmtg.com/mtg-set/commander-2014/">Commander 2014</a> | <a title="Khans of Tarkir MTG Art" href="https://www.artofmtg.com/mtg-set/khans-of-tarkir/">Khans of Tarkir</a> | <a title="From the Vault Annihilation MtG Art" href="https://www.artofmtg.com/mtg-set/from-the-vault-annihilation/">From the Vault: Annihilation</a> | <a title="M15 - Core Set MtG Art" href="https://www.artofmtg.com/mtg-set/m15-core-set/">Magic 2015</a> | <a title="Vintage Masters MtG Art" href="https://www.artofmtg.com/mtg-set/vintage-masters/">Vintage Masters</a> | <a title="Conspiracy MtG Art" href="https://www.artofmtg.com/mtg-set/conspiracy/">Conspiracy</a> | <a title="Journey into Nyx MtG Art" href="https://www.artofmtg.com/mtg-set/journey-into-nyx/">Journey into Nyx</a> | <a title="Born of the Gods Art" href="https://www.artofmtg.com/mtg-set/born-of-the-gods/">Born of the Gods</a> | <a title="Duel Decks: Jace vs. Vraska MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-jace-vs-vraska/">Duel Decks: Jace vs. Vraska</a> | <a title="Speed vs. Cunning MtG Art" href="https://www.artofmtg.com/mtg-set/speed-vs-cunning/">Duel Decks: Speed vs. Cunning</a></p>
<h2>2013</h2>
<p><a title="Commander 2013 Art" href="https://www.artofmtg.com/mtg-set/commander-2013/">Commander 2013</a> | <a title="Theros MtG Art" href="https://www.artofmtg.com/mtg-set/theros/">Theros</a> | <a title="M14 - Core Set MtG Art" href="https://www.artofmtg.com/mtg-set/m14-core-set/">Magic 2014</a> | <a title="Modern Masters MtG Art" href="https://www.artofmtg.com/mtg-set/modern-masters/">Modern Masters</a> | <a title="Dragon’s Maze MtG Art" href="https://www.artofmtg.com/mtg-set/dragons-maze/">Dragon’s Maze</a> | <a title="Gatecrash MtG Art" href="https://www.artofmtg.com/mtg-set/gatecrash/">Gatecrash</a> | <a title="Duel Decks: Heroes vs. Monsters MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-heroes-vs-monsters/">Duel Decks: Heroes vs. Monsters</a> | <a title="Duel Decks: Sorin vs. Tibalt MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-sorin-vs-tibalt/">Duel Decks: Sorin vs. Tibalt</a> | <a title="From the Vault: Twenty MtG Art" href="https://www.artofmtg.com/mtg-set/from-the-vault-twenty/">From the Vault: Twenty</a></p>
<h2>2012</h2>
<p><a title="Return to Ravnica MTG Art" href="https://www.artofmtg.com/mtg-set/return-to-ravnica/">Return to Ravnica</a> | From the Vault: Realms | <a title="M13 - Core Set MtG Art" href="https://www.artofmtg.com/mtg-set/m13-core-set/">Magic 2013</a> | <a title="Planechase 2012 MtG Art" href="https://www.artofmtg.com/mtg-set/planechase-2012-edition/">Planechase 2012</a> | <a title="Avacyn Restored Art" href="https://www.artofmtg.com/mtg-set/avacyn-restored/">Avacyn Restored</a> | <a title="Dark Ascension MtG Art" href="https://www.artofmtg.com/mtg-set/dark-ascension/">Dark Ascension</a> | <a title="Duel Decks: Izzet vs. Golgari MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-izzet-vs-golgari/">Duel Decks: Izzet vs. Golgari</a> | <a title="Duel Decks: Venser vs. Koth MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-venser-vs-koth/">Duel Decks: Venser vs. Koth</a></p>
<h2>2011</h2>
<p><a title="Innistrad MtG Art" href="https://www.artofmtg.com/mtg-set/innistrad/">Innistrad</a> | <a title="From the Vault: Legends MtG Art" href="https://www.artofmtg.com/mtg-set/from-the-vault-legends/">From the Vault: Legends</a> | <a title="M12 - Core Set MtG Art" href="https://www.artofmtg.com/mtg-set/m12-core-set/">Magic 2012</a> | <a title="Commander MtG Art" href="https://www.artofmtg.com/mtg-set/commander/">Commander</a> | <a title="New Phyrexia MTG Art" href="https://www.artofmtg.com/mtg-set/new-phyrexia/">New Phyrexia</a> | <a title="Mirrodin Besieged MtG Art" href="https://www.artofmtg.com/mtg-set/mirrodin-besieged/">Mirrodin Besieged</a> | <a title="Duel Decks: Ajani vs. Nicol Bolas MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-ajani-vs-nicol-bolas/">Duel Decks: Ajani vs. Nicol Bolas</a> | <a title="Graveborn MtG Art" href="https://www.artofmtg.com/mtg-set/graveborn/">Premium Deck Series: Graveborn</a></p>
<h2>2010</h2>
<p><a title="Scars of Mirrodin MtG Art" href="https://www.artofmtg.com/mtg-set/scars-of-mirrodin/">Scars of Mirrodin</a> | <a title="M11 - Core Set MtG Art" href="https://www.artofmtg.com/mtg-set/m11-core-set/">Magic 2011</a> | <a title="Rise of the Eldrazi MtG Art" href="https://www.artofmtg.com/mtg-set/rise-of-the-eldrazi/">Rise of the Eldrazi</a> | <a title="Worldwake MtG Art" href="https://www.artofmtg.com/mtg-set/worldwake/">Worldwake</a> | <a title="From the Vault: Relics MtG Art" href="https://www.artofmtg.com/mtg-set/from-the-vault-relics/">From the Vault: Relics</a></p>
<h2>2009</h2>
<p><a title="Zendikar MtG Art" href="https://www.artofmtg.com/mtg-set/zendikar/">Zendikar</a> | <a title="Planechase MtG Art" href="https://www.artofmtg.com/mtg-set/planechase/">Planechase</a> | <a title="Magic 2010 M10 - Core Set MtG Art" href="https://www.artofmtg.com/mtg-set/m10-core-set/">Magic 2010</a> | <a title="Alara Reborn Art" href="https://www.artofmtg.com/mtg-set/alara-reborn/">Alara Reborn</a> | <a title="Conflux MtG Art" href="https://www.artofmtg.com/mtg-set/conflux/">Conflux</a> | <a title="Duel Decks: Divine vs. Demonic MtG Art" href="https://www.artofmtg.com/mtg-set/duel-decks-divine-vs-demonic/">Duel Decks: Divine vs. Demonic</a></p>
<h2>2008</h2>
<p><a title="Shards of Alara MtG Art" href="https://www.artofmtg.com/mtg-set/shards-of-alara/">Shards of Alara</a> | <a title="Eventide MtG Art" href="https://www.artofmtg.com/mtg-set/eventide/">Eventide</a> | <a title="Shadowmoor MtG Art" href="https://www.artofmtg.com/mtg-set/shadowmoor/">Shadowmoor</a> | <a title="Morningtide MtG Art" href="https://www.artofmtg.com/mtg-set/morningtide/">Morningtide</a> | Duel Decks: Elspeth vs. Tezzeret</p>
<h2>2007</h2>
<p><a title="Lorwyn MtG Art" href="https://www.artofmtg.com/mtg-set/lorwyn/">Lorwyn</a> | <a title="Masters Edition MtG Art" href="https://www.artofmtg.com/mtg-set/masters-edition/">Masters Edition</a> | <a title="Tenth Edition MtG Art" href="https://www.artofmtg.com/mtg-set/tenth-edition/">Tenth Edition</a> | <a title="Future Sight MtG Art" href="https://www.artofmtg.com/mtg-set/future-sight/">Future Sight</a> | <a title="Planar Chaos MtG Art" href="https://www.artofmtg.com/mtg-set/planar-chaos/">Planar Chaos</a></p>
<h2>2006</h2>
<p><a title="Time Spiral MtG Art" href="https://www.artofmtg.com/mtg-set/time-spiral/">Time Spiral</a> | <a title="Coldsnap Art" href="https://www.artofmtg.com/mtg-set/coldsnap/">Coldsnap</a> | <a title="Dissension MtG Art" href="https://www.artofmtg.com/mtg-set/dissension/">Dissension</a> | <a title="Guildpact MtG Art" href="https://www.artofmtg.com/mtg-set/guildpact/">Guildpact</a></p>
<h2>2005</h2>
<p><a title="Ravnica: City of Guilds MTG Art" href="https://www.artofmtg.com/mtg-set/ravnica-city-of-guilds/">Ravnica: City of Guilds</a> | <a title="Ninth Edition MtG Art" href="https://www.artofmtg.com/mtg-set/ninth-edition/">Ninth Edition</a> | <a title="Saviors of Kamigawa MtG Art" href="https://www.artofmtg.com/mtg-set/saviors-of-kamigawa/">Saviors of Kamigawa</a> | <a title="Betrayers of Kamigawa MtG Art" href="https://www.artofmtg.com/mtg-set/betrayers-of-kamigawa/">Betrayers of Kamigawa</a></p>
<h2>2004</h2>
<p><a title="Unhinged MtG Art" href="https://www.artofmtg.com/mtg-set/unhinged/">Unhinged</a> | <a title="Champions of Kamigawa MtG Art" href="https://www.artofmtg.com/mtg-set/champions-of-kamigawa/">Champions of Kamigawa</a> | <a title="Fifth Dawn MtG Art" href="https://www.artofmtg.com/mtg-set/fifth-dawn/">Fifth Dawn</a> | <a title="Darksteel MtG Art" href="https://www.artofmtg.com/mtg-set/darksteel/">Darksteel</a></p>
<h2>2003</h2>
<p><a title="Mirrodin MtG Art" href="https://www.artofmtg.com/mtg-set/mirrodin/">Mirrodin</a> | <a title="Eighth Edition MtG Art" href="https://www.artofmtg.com/mtg-set/eighth-edition/">Eighth Edition</a> | <a title="Scourge MtG Art" href="https://www.artofmtg.com/mtg-set/scourge/">Scourge</a> | <a title="Legions MtG Art" href="https://www.artofmtg.com/mtg-set/legions/">Legions</a></p>
<h2>2002</h2>
<p><a title="Onslaught MtG Art" href="https://www.artofmtg.com/mtg-set/onslaught/">Onslaught</a> | Judgment | <a title="Torment MtG Art" href="https://www.artofmtg.com/mtg-set/torment/">Torment</a></p>
<h2>2001</h2>
<p><a title="Odyssey MtG Art" href="https://www.artofmtg.com/mtg-set/odyssey/">Odyssey</a> | <a title="Apocalypse MtG Art" href="https://www.artofmtg.com/mtg-set/apocalypse/">Apocalypse</a> | <a title="Seventh Edition MtG Art" href="https://www.artofmtg.com/mtg-set/seventh-edition/">Seventh Edition</a> | <a title="Planeshift MtG Art" href="https://www.artofmtg.com/mtg-set/planeshift/">Planeshift</a></p>
<h2>2000</h2>
<p><a title="Invasion MtG Art" href="https://www.artofmtg.com/mtg-set/invasion/">Invasion</a> | <a title="Prophecy MtG Art" href="https://www.artofmtg.com/mtg-set/prophecy/">Prophecy</a> | Nemesis</p>
<h2>1999</h2>
<p><a title="Mercadian Masques MtG Art" href="https://www.artofmtg.com/mtg-set/mercadian-masques/">Mercadian Masques</a> | <a title="Urza's Destiny MtG Art" href="https://www.artofmtg.com/mtg-set/urzas-destiny/">Urza’s Destiny</a> | Portal Three Kingdoms | <a title="Sixth Edition MtG Art" href="https://www.artofmtg.com/mtg-set/sixth-edition/">Sixth Edition</a> | <a title="Urza's Legacy MtG Art" href="https://www.artofmtg.com/mtg-set/urzas-legacy/">Urza’s Legacy</a></p>
<h2>1998</h2>
<p>Urza’s Saga | Unglued | <a title="Portal Second Age MtG Art" href="https://www.artofmtg.com/mtg-set/portal-second-age/">Portal Second Age</a> | <a title="Exodus MtG Art" href="https://www.artofmtg.com/mtg-set/exodus/">Exodus</a> | <a title="Stronghold MtG Art" href="https://www.artofmtg.com/mtg-set/stronghold/">Stronghold</a></p>
<h2>1997</h2>
<p>Tempest | Weatherlight | <a title="Portal MtG Art" href="https://www.artofmtg.com/mtg-set/portal/">Portal</a> | <a title="Fifth Edition MtG Art" href="https://www.artofmtg.com/mtg-set/fifth-edition/">Fifth Edition</a> | <a title="Visions MtG Art" href="https://www.artofmtg.com/mtg-set/visions/">Visions</a></p>
<h2>1996</h2>
<p><a title="Mirage MtG Art" href="https://www.artofmtg.com/mtg-set/mirage/">Mirage</a> | <a title="Alliances MtG Art" href="https://www.artofmtg.com/mtg-set/alliances/">Alliances</a></p>
<h2>1995</h2>
<p>Homelands | <a title="Ice Age MtG Art" href="https://www.artofmtg.com/mtg-set/ice-age/">Ice Age</a> | <a title="Fourth Edition MtG Art" href="https://www.artofmtg.com/mtg-set/fourth-edition/">Fourth Edition</a></p>
<h2>1994</h2>
<p>Fallen Empires | <a title="The Dark MtG Art" href="https://www.artofmtg.com/mtg-set/the-dark/">The Dark</a> | Legends | <a title="Revised Edition MtG Art" href="https://www.artofmtg.com/mtg-set/revised-edition/">Revised Edition</a> | <a title="Antiquities MtG Art" href="https://www.artofmtg.com/mtg-set/antiquities/">Antiquities</a></p>
<h2>1993</h2>
<p><a title="Arabian Nights MtG Art" href="https://www.artofmtg.com/mtg-set/arabian-nights/">Arabian Nights</a> | Unlimited Edition | Beta (Limited Edition) | <a title="Alpha MtG Art" href="https://www.artofmtg.com/mtg-set/alpha/">Alpha (Limited Edition)</a></p>
"""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/128.0.0.0 Safari/537.36"
    )
}


def extract_set_links(html: str) -> list[dict]:
  soup = BeautifulSoup(html, "html.parser")
  sets = []
  seen_urls = set()

  for a in soup.find_all("a", href=True):
    url = a["href"].strip()
    name = a.get_text(strip=True).strip("|").strip()
    if not name or url in seen_urls:
      continue
    seen_urls.add(url)
    sets.append({"set_name": name, "url": url})
  return sets


def scrape_set(session: requests.Session, set_name: str, base_url: str) -> list[dict]:
  results = []
  page = 1

  while True:
    url = base_url if page == 1 else f"{base_url.rstrip('/')}/page/{page}/"
    try:
      resp = session.get(url, headers=HEADERS, timeout=15)
      if resp.status_code == 404:
        break
      resp.raise_for_status()
    except requests.RequestException as e:
      print(f"  [!] Error en {url}: {e}")
      break

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select(".artwork-card")
    if not cards:
      break

    for card in cards:
      title_el = card.select_one("h4")
      img_el = card.select_one("img")
      if not title_el or not img_el:
        continue

      card_name = title_el.get_text(strip=True)
      thumb_url = img_el.get("data-src") or img_el.get("src") or ""

      # Eliminar dimensiones de WordPress (ej. -300x300) para obtener la URL original
      highres_url = re.sub(r"-\d+x\d+(?=\.[a-zA-Z]+$)", "", thumb_url)

      results.append({
          "name": card_name,
          "set": set_name,
          "image_url": highres_url,
      })

    print(f"  -> Página {page}: {len(cards)} cartas extraídas")
    page += 1
    time.sleep(0.5)  # Pausa breve para no saturar el servidor

  return results


def main():
  sets = extract_set_links(SETS_HTML)
  print(f"Total de sets con enlace encontrados: {len(sets)}\n")

  all_cards = []
  with requests.Session() as session:
    for idx, s in enumerate(sets, 1):
      print(f"[{idx}/{len(sets)}] Procesando: {s['set_name']} ({s['url']})")
      cards = scrape_set(session, s["set_name"], s["url"])
      all_cards.extend(cards)

  output_file = "artofmtg_cards.json"
  with open(output_file, "w", encoding="utf-8") as f:
    json.dump(all_cards, f, indent=2, ensure_ascii=False)

  print(f"\nListo. Se guardaron {len(all_cards)} cartas en '{output_file}'.")


if __name__ == "__main__":
  main()