"""
EMMMA Brand Partnership System — Sections C, D, E update.
Updates Instagram handles, outreach method, and PR contact notes for all brand records.
Run from rollon/ directory: python3 update_brands.py
"""
import os, sys, json, re

sys.path.insert(0, os.path.dirname(__file__))
from modules.google_sheets import SheetsManager
from datetime import datetime

GOOGLE_SHEET_ID = os.environ.get('ROLLON_SHEET_ID', '17b7HjbfXkV5w_Q8lRuG3Ae_7hwJ0M9F7ODVIFytBBmY')
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), 'credentials.json')
TOKEN_PATH = os.path.join(os.path.dirname(__file__), 'token.json')
if not os.path.exists(TOKEN_PATH):
    TOKEN_PATH = os.path.join(os.path.dirname(__file__), '..', 'token.json')

sheets = SheetsManager(GOOGLE_SHEET_ID, CREDENTIALS_PATH, TOKEN_PATH)

# ── Brand data: Instagram handles, outreach method, PR agency notes ────
BRAND_DATA = {
    # === FASHION ===
    "AllSaints": {"ig": "@allsaints", "outreach": "Both", "pr_notes": "PR: Purple PR (UK). Check allsaints.com/contact for partnerships."},
    "Cheap Monday": {"ig": "@cheapmonday", "outreach": "DM", "pr_notes": "Brand discontinued by H&M Group ~2019. Account may be inactive."},
    "Converse": {"ig": "@converse", "outreach": "Email", "pr_notes": "PR: Nike Communications. Has active music program (Converse Rubber Tracks). Try converse.com/press."},
    "Doc Martens": {"ig": "@drmartensofficial", "outreach": "Email", "pr_notes": "PR: Exposure (UK). Strong music heritage. Check drmartens.com/press."},
    "Dr. Denim": {"ig": "@drdenimjeans", "outreach": "DM", "pr_notes": "Swedish denim brand. Small team. Check drdenim.com for press contact. Email needed."},
    "Free People": {"ig": "@freepeople", "outreach": "Both", "pr_notes": "Owned by URBN. PR in-house. Check freepeople.com/press. Email needed."},
    "Ganni": {"ig": "@ganni", "outreach": "Both", "pr_notes": "PR: KCD (US), Karla Otto (intl). Danish brand. Check ganni.com/press. Email needed."},
    "Killstar": {"ig": "@killstarco", "outreach": "DM", "pr_notes": "Gothic/alt fashion. Small in-house team. Check killstar.com/pages/contact. Email needed."},
    "Levi's": {"ig": "@levis", "outreach": "Email", "pr_notes": "PR: HL Group (US). Has Levi's Music Project. Strong opportunity. Check levistrauss.com/newsroom/contacts."},
    "Lisa Says Gah": {"ig": "@lisasaysgah", "outreach": "DM", "pr_notes": "Small indie brand, SF-based. In-house PR. Check lisasaysgah.com/pages/contact. Email needed."},
    "Madewell": {"ig": "@madewell", "outreach": "Both", "pr_notes": "Owned by J.Crew Group. Has done music campaigns. Check madewell.com/press. Email needed."},
    "Monki": {"ig": "@monki", "outreach": "DM", "pr_notes": "Owned by H&M Group. PR through H&M Group comms. Check monki.com/press. Email needed."},
    "Nasty Gal": {"ig": "@nastygal", "outreach": "Both", "pr_notes": "Owned by Boohoo Group. PR routed through Boohoo Group comms. Email needed."},
    "Nudie Jeans": {"ig": "@nudiejeans", "outreach": "DM", "pr_notes": "Swedish sustainability brand. Check nudiejeans.com/press. Email needed."},
    "Reformation": {"ig": "@reformation", "outreach": "Both", "pr_notes": "PR: Black Frame. LA-based. Active celebrity/music dressing. Check thereformation.com/pages/press."},
    "Stussy": {"ig": "@stussy", "outreach": "Both", "pr_notes": "Deep music/streetwear roots. Selective with partnerships. Check stussy.com/pages/contact. Email needed."},
    "The Kooples": {"ig": "@thekooples", "outreach": "Both", "pr_notes": "French brand with rock/music DNA. Has done musician collabs. Check thekooples.com/press. Email needed."},
    "The Ragged Priest": {"ig": "@theraggedpriest", "outreach": "DM", "pr_notes": "UK indie brand. Small team. Check theraggedpriest.com/pages/contact. Email needed."},
    "UNIF": {"ig": "@unif", "outreach": "DM", "pr_notes": "LA-based indie. Small operation. Check unif.com for contact. Email needed."},
    "Urban Outfitters": {"ig": "@urbanoutfitters", "outreach": "Both", "pr_notes": "Owned by URBN. Has vinyl/music in-store program. Check urbanoutfitters.com/press or urbn.com/press."},
    "Weekday": {"ig": "@weekday_stores", "outreach": "DM", "pr_notes": "Owned by H&M Group. PR through H&M Group comms. Check weekday.com/press. Email needed."},
    "Chanel": {"ig": "@chanelofficial", "outreach": "Email", "pr_notes": "In-house PR. Pharrell creative director ties. Highly selective. Check chanel.com/us/about-chanel/contact."},
    "Gucci": {"ig": "@gucci", "outreach": "Email", "pr_notes": "PR: In-house (Kering Group), KCD. Active music partnerships. Check gucci.com/press or kering.com/en/group/contacts."},
    "Dior": {"ig": "@dior", "outreach": "Email", "pr_notes": "PR: In-house (LVMH). Extensive music/celebrity dressing. Check dior.com/press. Email needed."},
    "Prada": {"ig": "@prada", "outreach": "Email", "pr_notes": "PR: In-house, KCD (US). Has Prada Mode cultural events. Check pradagroup.com/en/press.html."},
    "Hermes": {"ig": "@hermes", "outreach": "Email", "pr_notes": "In-house PR. Most selective luxury house. Rarely does external partnerships. Check hermes.com/press."},
    "Louis Vuitton": {"ig": "@louisvuitton", "outreach": "Email", "pr_notes": "PR: In-house (LVMH). Pharrell as men's CD. Strong opportunity but selective. Check louisvuitton.com/press."},
    "Saint Laurent": {"ig": "@saintlaurent", "outreach": "Email", "pr_notes": "PR: In-house (Kering). Deep music DNA (SL music program). Strong fit. Check ysl.com/press."},
    "Balenciaga": {"ig": "@balenciaga", "outreach": "Email", "pr_notes": "PR: In-house (Kering). Active in music/culture. Check balenciaga.com/press. Email needed."},
    "Givenchy": {"ig": "@givenchy", "outreach": "Email", "pr_notes": "PR: In-house (LVMH). History of music partnerships. Check givenchy.com/press. Email needed."},
    "Bottega Veneta": {"ig": "@bottegaveneta", "outreach": "Email", "pr_notes": "PR: In-house (Kering). Verify IG is active (was deleted in 2021, relaunched). Check bottegaveneta.com/press."},
    "ASOS": {"ig": "@asos", "outreach": "Both", "pr_notes": "Large in-house PR team. Has done music partnerships. Check asos.com/about/press. Email needed."},
    "Depop": {"ig": "@depop", "outreach": "DM", "pr_notes": "Owned by Etsy. Active in music/youth culture. Check depop.com/press. Email needed."},
    "Msbhv": {"ig": "@msbhv", "outreach": "DM", "pr_notes": "Polish streetwear/club culture brand. Strong music ties. Small team. Check misbhv.com/pages/contact. Email needed."},
    "Diesel": {"ig": "@diesel", "outreach": "Both", "pr_notes": "PR: In-house (OTB Group). Active music/culture partnerships. Check diesel.com/press or otb.net/contacts."},
    "Acne": {"ig": "@acnestudios", "outreach": "Both", "pr_notes": "PR: Karla Otto (intl). Swedish brand with music/art crossover. Check acnestudios.com/press."},

    # === FOOTWEAR ===
    "Adidas": {"ig": "@adidas", "outreach": "Email", "pr_notes": "Major corporate. Formal PR dept. Check adidas.com/press. Email needed."},
    "Nike": {"ig": "@nike", "outreach": "Email", "pr_notes": "Major corporate. Formal PR dept. Check news.nike.com/press-contacts. Email needed."},
    "Puma": {"ig": "@puma", "outreach": "Email", "pr_notes": "Major corporate. Check about.puma.com/en/press. Email needed."},
    "New Balance": {"ig": "@newbalance", "outreach": "Email", "pr_notes": "Corporate PR. Check newbalance.com/press. Email needed."},
    "Solomon": {"ig": "@salomon", "outreach": "Email", "pr_notes": "Trail/outdoor brand (Amer Sports). Check salomon.com/press. Email needed."},
    "Asics": {"ig": "@asics", "outreach": "Email", "pr_notes": "Corporate PR. Check asics.com/press. Email needed."},
    "Hoka": {"ig": "@hoka", "outreach": "Both", "pr_notes": "Growing brand (Deckers). More accessible for collabs. Check hoka.com/press. Email needed."},
    "Under Armour": {"ig": "@underarmour", "outreach": "Email", "pr_notes": "Corporate PR. Check underarmour.com/press. Email needed."},
    "Reebok": {"ig": "@reebok", "outreach": "Email", "pr_notes": "Corporate PR. Check reebok.com/press. Email needed."},
    "Vans": {"ig": "@vans", "outreach": "Email", "pr_notes": "Strong music heritage. Vans Warped Tour history. Check vans.com/press. Email needed."},
    "Columbia": {"ig": "@columbia1938", "outreach": "Both", "pr_notes": "Mid-tier outdoor. Check columbia.com/press. Email needed."},
    "Patagonia": {"ig": "@patagonia", "outreach": "Email", "pr_notes": "Environmental focus. Has music/activism ties. Check patagonia.com/press. Email needed."},
    "The North Face": {"ig": "@thenorthface", "outreach": "Email", "pr_notes": "VF Corporation. Check thenorthface.com/press. Email needed."},
    "Allbirds": {"ig": "@allbirds", "outreach": "Both", "pr_notes": "Sustainability brand. Accessible for collabs. Check allbirds.com/press. Email needed."},
    "On Running": {"ig": "@on", "outreach": "Both", "pr_notes": "Swiss running brand. Growing cultural presence. Check on-running.com/press. Email needed."},
    "Veja": {"ig": "@veja", "outreach": "Both", "pr_notes": "French sustainability sneaker. Check veja-store.com/press. Email needed."},
    "Rothy's": {"ig": "@rothys", "outreach": "Both", "pr_notes": "Sustainable footwear. Check rothys.com/press. Email needed."},
    "Vivobarefoot": {"ig": "@vivobarefoot", "outreach": "DM", "pr_notes": "Niche barefoot brand. Small team. Check vivobarefoot.com/press. Email needed."},
    "Altra": {"ig": "@altrarunning", "outreach": "DM", "pr_notes": "Niche running brand. Community-focused. Check altrarunning.com/press. Email needed."},

    # === COSMETICS ===
    "Anastasia Beverly Hills": {"ig": "@anastasiabeverlyhills", "outreach": "Email", "pr_notes": "PR: Black Frame. Check anastasia.com/pages/contact. Email needed."},
    "bareMinerals": {"ig": "@bareminerals", "outreach": "Both", "pr_notes": "Owned by Orveon. Check bareminerals.com/contact-us. Email needed."},
    "Benefit": {"ig": "@benefitcosmetics", "outreach": "Email", "pr_notes": "LVMH-owned. In-house PR. Check benefitcosmetics.com/contact. Email needed."},
    "Bobbi Brown": {"ig": "@bobbibrown", "outreach": "Email", "pr_notes": "Estée Lauder Companies. PR through ELC corporate. Email needed."},
    "Charlotte Tilbury": {"ig": "@charlottetilbury", "outreach": "Email", "pr_notes": "Owned by Puig. In-house + The Communications Store. Check charlottetilbury.com/us/contact-us."},
    "Clinique": {"ig": "@clinique", "outreach": "Email", "pr_notes": "Estée Lauder Companies. PR through ELC. Check clinique.com/contact. Email needed."},
    "Fenty Beauty": {"ig": "@fentybeauty", "outreach": "Email", "pr_notes": "LVMH/Kendo. Strong music ties via Rihanna. Check fentybeauty.com/pages/contact. Email needed."},
    "Glossier": {"ig": "@glossier", "outreach": "Both", "pr_notes": "In-house PR. Check glossier.com/pages/contact. Email needed."},
    "Haus Labs": {"ig": "@hauslabs", "outreach": "Both", "pr_notes": "Lady Gaga's brand. PR: BPCM. Strong music angle. Check hauslabs.com/pages/contact. Email needed."},
    "Hourglass": {"ig": "@hourglasscosmetics", "outreach": "Email", "pr_notes": "Unilever-owned. PR through parent structure. Email needed."},
    "Huda Beauty": {"ig": "@hudabeauty", "outreach": "Email", "pr_notes": "PR: SEEN Group. Independent brand. Check hudabeauty.com for press. Email needed."},
    "MAC": {"ig": "@maccosmetics", "outreach": "Email", "pr_notes": "Estée Lauder Companies. Extensive musician collab history. PR through ELC. Email needed."},
    "NARS": {"ig": "@narsissist", "outreach": "Email", "pr_notes": "Shiseido-owned. PR through Shiseido Americas. Email needed."},
    "Pat McGrath": {"ig": "@patmcgrathreal", "outreach": "Email", "pr_notes": "PR: KCD. Strong fashion/music crossover. Check patmcgrath.com/pages/contact. Email needed."},
    "Rare Beauty": {"ig": "@rarebeauty", "outreach": "Both", "pr_notes": "Selena Gomez's brand. PR: BPCM. Strong music partnership potential. Check rarebeauty.com/pages/contact."},
    "Sephora": {"ig": "@sephora", "outreach": "Email", "pr_notes": "LVMH retailer. Large in-house PR/partnerships team. Check sephora.com/beauty/contact-us. Email needed."},
    "Sol de Janeiro": {"ig": "@soldejaneiro", "outreach": "Both", "pr_notes": "PR: Shadow PR / M18. L'Occitane Group. Brazilian brand — strong EMMMA alignment. Check soldejaneiro.com/pages/contact."},
    "Tarte": {"ig": "@tartecosmetics", "outreach": "Both", "pr_notes": "PR: MKG. Independent brand. Check tartecosmetics.com/contact-us. Email needed."},
    "Too Faced": {"ig": "@toofaced", "outreach": "Both", "pr_notes": "Estée Lauder Companies. Check toofaced.com/contact-us. Email needed."},
    "Urban Decay": {"ig": "@urbandecaycosmetics", "outreach": "Both", "pr_notes": "L'Oréal-owned. History of music/festival partnerships. Check urbandecay.com/contact. Email needed."},
    "La Mer": {"ig": "@labormer", "outreach": "Email", "pr_notes": "Estée Lauder Companies luxury. PR through ELC corporate. Email needed."},
    "SK-II": {"ig": "@skiiglobal", "outreach": "Email", "pr_notes": "Procter & Gamble. PR through P&G Beauty. Email needed."},
    "Milk Makeup": {"ig": "@milkmakeup", "outreach": "DM", "pr_notes": "PR: Shadow PR. Born from Milk Studios (strong music ties). Check milkmakeup.com/pages/contact. Email needed."},
    "Lime Crime": {"ig": "@limecrimemakeup", "outreach": "DM", "pr_notes": "Indie brand. Check limecrime.com/pages/contact. Email needed."},
    "The Ordinary": {"ig": "@theordinary", "outreach": "Both", "pr_notes": "DECIEM / Estée Lauder. PR through DECIEM in-house. Email needed."},
    "Glow Recipe": {"ig": "@glowrecipe", "outreach": "Both", "pr_notes": "PR: BPCM. K-beauty inspired indie. Check glowrecipe.com/pages/contact. Email needed."},
    "Byredo": {"ig": "@byredo", "outreach": "Email", "pr_notes": "Puig-owned. PR: Purple PR. Luxury positioning. Check byredo.com/contact. Email needed."},
    "Le Labo": {"ig": "@lelabofragrances", "outreach": "Email", "pr_notes": "Estée Lauder Companies. PR through ELC. Email needed."},
    "Tom Ford Beauty": {"ig": "@tomfordbeauty", "outreach": "Email", "pr_notes": "Estée Lauder Companies luxury. PR through ELC. Email needed."},
    "Kosas": {"ig": "@kosas", "outreach": "DM", "pr_notes": "PR: Shadow PR. Clean beauty indie. Check kosas.com/pages/contact. Email needed."},
    "Saie": {"ig": "@saiebeauty", "outreach": "DM", "pr_notes": "PR: BPCM. Clean beauty indie. Check saiebeauty.com for contact. Email needed."},
    "Freck": {"ig": "@frfreck", "outreach": "DM", "pr_notes": "Small indie brand. Check frfreck.com for contact. Email needed."},
    "Refy": {"ig": "@refybeauty", "outreach": "DM", "pr_notes": "UK-based indie. Check refybeauty.com for press. Email needed."},
    "Westman Atelier": {"ig": "@westman_atelier", "outreach": "DM", "pr_notes": "PR: Purple PR. Founded by Gucci Westman. Check westman-atelier.com/pages/contact. Email needed."},
    "Youth To The People": {"ig": "@youthtothepeople", "outreach": "Both", "pr_notes": "L'Oréal-owned. Check youthtothepeople.com/pages/contact. Email needed."},
    "Laneige": {"ig": "@laboraneige_us", "outreach": "Both", "pr_notes": "Amorepacific. US PR through Amorepacific US. Check laneige.com/us/contact. Email needed."},
    "Dr. Jart": {"ig": "@drjart", "outreach": "Both", "pr_notes": "Estée Lauder (via Have & Be). PR through ELC. Email needed."},
    "Buxom": {"ig": "@buxomcosmetics", "outreach": "Both", "pr_notes": "Orveon-owned. Check buxomcosmetics.com/contact. Email needed."},
    "Iconic London": {"ig": "@iconiclondoninc", "outreach": "DM", "pr_notes": "UK-based brand. Check iconiclondoninc.com for press. Email needed."},
    "IT Cosmetics": {"ig": "@itcosmetics", "outreach": "Both", "pr_notes": "L'Oréal-owned. PR through L'Oréal USA. Check itcosmetics.com/contact-us. Email needed."},
    "Smashbox": {"ig": "@smashboxcosmetics", "outreach": "Both", "pr_notes": "Estée Lauder Companies. Founded from Smashbox Studios. PR through ELC. Email needed."},
    "Valentino": {"ig": "@maisonvalentino", "outreach": "Email", "pr_notes": "L'Oréal holds beauty license. PR through L'Oréal Luxe. Email needed."},
    "La Prairie": {"ig": "@laprairie", "outreach": "Email", "pr_notes": "Beiersdorf-owned ultra-luxury. Check laprairie.com/contact. Email needed."},
    "Sisley": {"ig": "@sisleyparis", "outreach": "Email", "pr_notes": "Family-owned French luxury. PR: KCD. Check sisley-paris.com/en-US/contact. Email needed."},
    "Guerlain": {"ig": "@guerlain", "outreach": "Email", "pr_notes": "LVMH luxury. PR through LVMH/Guerlain comms. Email needed."},
    "Cle de Peau": {"ig": "@cledepeaubeaute", "outreach": "Email", "pr_notes": "Shiseido ultra-luxury. PR through Shiseido corporate. Email needed."},
    "Chantecaille": {"ig": "@chantecaille", "outreach": "Email", "pr_notes": "PR: Purple PR / BPCM. Luxury family-owned. Check chantecaille.com/pages/contact. Email needed."},

    # === FRAGRANCE ===
    "DS & Durga": {"ig": "@dsanddurga", "outreach": "DM", "pr_notes": "Brooklyn-based indie. Small team. Strong creative/music alignment. Email needed."},
    "Imaginary Authors": {"ig": "@imaginaryauthors", "outreach": "DM", "pr_notes": "Portland indie fragrance. Creative storytelling brand. Small team. Email needed."},
    "Maison Margiela": {"ig": "@maisonmargiela", "outreach": "Email", "pr_notes": "OTB Group. Formal PR. Check maisonmargiela.com/press. Email needed."},
    "Phlur": {"ig": "@phlur", "outreach": "DM", "pr_notes": "Indie fragrance. Check phlur.com for contact. Email needed."},
    "Skylar": {"ig": "@skylar", "outreach": "DM", "pr_notes": "Clean fragrance brand. Check skylar.com for contact. Email needed."},
    "Henry Rose": {"ig": "@henryrose", "outreach": "DM", "pr_notes": "Michelle Pfeiffer's brand. Clean fragrance. Check henryrose.com for contact. Email needed."},
    "Boy Smells": {"ig": "@boysmells", "outreach": "DM", "pr_notes": "Gender-fluid fragrance/candle brand. Check boysmells.com for contact. Email needed."},
    "DedCool": {"ig": "@dedcool", "outreach": "DM", "pr_notes": "LA-based indie fragrance. Check dedcool.com for contact. Email needed."},

    # === MUSIC TECH ===
    "Ableton": {"ig": "@ableton", "outreach": "Both", "pr_notes": "Music software. Has artist partnership program. Check ableton.com/press. Email needed."},
    "Fender": {"ig": "@fender", "outreach": "Both", "pr_notes": "Strong artist endorsement program. Check fender.com/press. Email needed."},
    "Gibson": {"ig": "@gibsonguitar", "outreach": "Both", "pr_notes": "Artist relations program. Check gibson.com/press. Email needed."},
    "Korg": {"ig": "@korgofficial", "outreach": "Both", "pr_notes": "Japanese music tech. Check korg.com/press. Email needed."},
    "Moog": {"ig": "@maboroonakossynthesizers", "outreach": "DM", "pr_notes": "Boutique synth maker. Artist-friendly. Check maboronakoss.com/press. Email needed."},
    "Roland": {"ig": "@rolandglobal", "outreach": "Both", "pr_notes": "Has artist program. Check roland.com/press. Email needed."},
    "Sennheiser": {"ig": "@sennheiser", "outreach": "Email", "pr_notes": "Premium audio. Formal PR. Check sennheiser.com/press. Email needed."},
    "Shure": {"ig": "@shaboronakos", "outreach": "Both", "pr_notes": "Pro audio. Has artist relations. Check shaboronakos.com/press. Email needed."},
    "Beats by Dre": {"ig": "@beatsbydre", "outreach": "Email", "pr_notes": "Apple-owned. Strong music partnerships. Formal PR. Email needed."},
    "Sony": {"ig": "@sony", "outreach": "Email", "pr_notes": "Major corp. Formal PR. Check sony.com/press. Email needed."},
    "Bose": {"ig": "@bose", "outreach": "Email", "pr_notes": "Premium audio. Formal PR. Check bose.com/press. Email needed."},
    "Audio-Technica": {"ig": "@audiotechnicausa", "outreach": "Both", "pr_notes": "Pro audio. Artist-friendly. Check audio-technica.com/press. Email needed."},
    "Taylor": {"ig": "@taylorguitars", "outreach": "Both", "pr_notes": "Artist relations program. Check taylorguitars.com/press. Email needed."},
    "Nord": {"ig": "@nordkeyboards", "outreach": "DM", "pr_notes": "Swedish keyboards. Niche. Check nordkeyboards.com. Email needed."},
    "Neumann": {"ig": "@neumann.berlin", "outreach": "DM", "pr_notes": "Pro microphones (Sennheiser Group). Check neumann.com/press. Email needed."},
    "Yamaha": {"ig": "@yamahamusicusa", "outreach": "Email", "pr_notes": "Major corp. Formal PR. Check yamaha.com/press. Email needed."},
    "Behringer": {"ig": "@behringer", "outreach": "Both", "pr_notes": "Music Tribe Group. Accessible. Check behringer.com. Email needed."},
    "AKG": {"ig": "@akgaudio", "outreach": "Both", "pr_notes": "Samsung/Harman. Pro audio. Check akg.com/press. Email needed."},
    "Apollo Universal Audio": {"ig": "@universalaudio", "outreach": "Both", "pr_notes": "Pro audio interfaces. Artist-friendly. Check uaudio.com/press. Email needed."},

    # === LIFESTYLE ===
    "Polaroid": {"ig": "@polaroid", "outreach": "Both", "pr_notes": "Iconic brand. Creative partnerships. Check polaroid.com/press. Email needed."},
    "Urbanears": {"ig": "@urbanears", "outreach": "DM", "pr_notes": "Swedish headphones. Music-focused. Small team. Check urbanears.com/press. Email needed."},
    "Bang & Olufsen": {"ig": "@bangolufsen", "outreach": "Email", "pr_notes": "Danish luxury audio. Formal PR. Check bang-olufsen.com/press. Email needed."},
    "Aesop": {"ig": "@aesopskincare", "outreach": "Email", "pr_notes": "L'Oréal-owned. Premium positioning. Check aesop.com/contact. Email needed."},
    "Dyson": {"ig": "@dyson", "outreach": "Email", "pr_notes": "Major corp. Formal PR. Check dyson.com/press. Email needed."},
    "Leica": {"ig": "@leica_camera", "outreach": "Email", "pr_notes": "German luxury camera. Formal PR. Check leica-camera.com/press. Email needed."},
    "Apple": {"ig": "@apple", "outreach": "Email", "pr_notes": "Major corp. Apple Music partnerships team. Check apple.com/pr. Email needed."},
    "Rimowa": {"ig": "@rimowa", "outreach": "Email", "pr_notes": "LVMH-owned luxury luggage. Check rimowa.com/press. Email needed."},
    "Diptyque": {"ig": "@diptyque", "outreach": "Email", "pr_notes": "French luxury candles/fragrance. Check diptyqueparis.com/press. Email needed."},
    "Rolex": {"ig": "@rolex", "outreach": "Email", "pr_notes": "Ultra-luxury. Very selective. Formal PR only. Email needed."},
    "Smeg": {"ig": "@smeg", "outreach": "Both", "pr_notes": "Italian appliance brand. Check smeg.com/press. Email needed."},
    "Vitra": {"ig": "@vitra", "outreach": "DM", "pr_notes": "Swiss design furniture. Check vitra.com/press. Email needed."},
    "Assouline": {"ig": "@assouline", "outreach": "DM", "pr_notes": "Luxury publishing. Art/culture focused. Check assouline.com/press. Email needed."},

    # === BEVERAGES ===
    "Red Bull": {"ig": "@redbull", "outreach": "Email", "pr_notes": "Red Bull Music. Major music program. Check redbull.com/press. Strong opportunity. Email needed."},
    "Liquid Death": {"ig": "@liquiddeath", "outreach": "Both", "pr_notes": "Has active music/punk marketing. Very brand-forward. Check liquiddeath.com/press. Email needed."},
    "Topo Chico": {"ig": "@topochicousa", "outreach": "Both", "pr_notes": "Coca-Cola owned. Check topochico.com. Email needed."},
    "Oatly": {"ig": "@oatly", "outreach": "Both", "pr_notes": "Creative brand marketing. Check oatly.com/press. Email needed."},
    "White Claw": {"ig": "@whiteclaw", "outreach": "Both", "pr_notes": "Mark Anthony Brands. Festival/event marketing. Check whiteclaw.com/press. Email needed."},
    "Casamigos": {"ig": "@casamigos", "outreach": "Email", "pr_notes": "Diageo-owned. Celebrity brand. Formal PR. Email needed."},
    "Hendrick's": {"ig": "@hendricksgin", "outreach": "Both", "pr_notes": "William Grant & Sons. Creative marketing. Check hendricksgin.com. Email needed."},
    "Aperol": {"ig": "@aperolspritzofficial", "outreach": "Both", "pr_notes": "Campari Group. Festival/event marketing. Check aperol.com. Email needed."},

    # === MEDIA ===
    "Notion": {"ig": "@notionmagazine", "outreach": "DM", "pr_notes": "UK music/culture magazine. Accessible for emerging artists. Email needed."},
    "The Face": {"ig": "@thefacemagazine", "outreach": "DM", "pr_notes": "UK culture magazine. Relaunched. Check theface.com/contact. Email needed."},
    "Vogue": {"ig": "@voguemagazine", "outreach": "Email", "pr_notes": "Condé Nast. Formal PR. Check vogue.com/contact. Email needed."},
    "Dazed": {"ig": "@daboronakoszed", "outreach": "DM", "pr_notes": "UK culture magazine. Check daboronakoszeddigital.com/contact. Email needed."},
    "i-D": {"ig": "@i_d", "outreach": "DM", "pr_notes": "Vice Media. Youth culture. Check i-d.vice.com/contact. Email needed."},
    "Pitchfork": {"ig": "@pitchfork", "outreach": "Both", "pr_notes": "Condé Nast music. Check pitchfork.com/contact. Email needed."},
    "Rolling Stone": {"ig": "@rollingstone", "outreach": "Email", "pr_notes": "Penske Media. Formal PR. Check rollingstone.com/contact. Email needed."},
    "NME": {"ig": "@nmemagazine", "outreach": "DM", "pr_notes": "UK music media. Check nme.com/contact. Email needed."},
    "The Fader": {"ig": "@thefader", "outreach": "DM", "pr_notes": "Independent music/culture. Check thefader.com/contact. Email needed."},
    "Hypebeast": {"ig": "@hypebeast", "outreach": "Both", "pr_notes": "Streetwear/culture media. Check hypebeast.com/contact. Email needed."},
    "Highsnobiety": {"ig": "@highsnobiety", "outreach": "Both", "pr_notes": "Streetwear/culture media. Check highsnobiety.com/contact. Email needed."},
    "Complex": {"ig": "@complex", "outreach": "Both", "pr_notes": "BuzzFeed Inc. Culture/music. Check complex.com/contact. Email needed."},
    "Refinery29": {"ig": "@refinery29", "outreach": "Both", "pr_notes": "Vice Media. Check refinery29.com/contact. Email needed."},
    "Allure": {"ig": "@allaboronakos", "outreach": "Both", "pr_notes": "Condé Nast beauty. Check allaboronakos.com/contact. Email needed."},
    "Byrdie": {"ig": "@byrdie", "outreach": "DM", "pr_notes": "Dotdash Meredith. Beauty/wellness. Check byrdie.com/contact. Email needed."},
    "Elle": {"ig": "@ellemagazine", "outreach": "Email", "pr_notes": "Hearst. Formal PR. Check elle.com/contact. Email needed."},
    "Harper's Bazaar": {"ig": "@harpersbazaarus", "outreach": "Email", "pr_notes": "Hearst. Formal PR. Check harpersbazaar.com/contact. Email needed."},
    "GQ": {"ig": "@gq", "outreach": "Email", "pr_notes": "Condé Nast. Formal PR. Check gq.com/contact. Email needed."},
    "Esquire": {"ig": "@esquire", "outreach": "Email", "pr_notes": "Hearst. Formal PR. Check esquire.com/contact. Email needed."},
    "Into the Gloss": {"ig": "@intothegloss", "outreach": "DM", "pr_notes": "Glossier's media arm. Check intothegloss.com. Email needed."},
    "Goop": {"ig": "@goop", "outreach": "Both", "pr_notes": "Gwyneth Paltrow's brand. Check goop.com/press. Email needed."},
    "Stereogum": {"ig": "@stereogum", "outreach": "DM", "pr_notes": "Independent music blog. Check stereogum.com/contact. Email needed."},
    "The Hundreds": {"ig": "@thehundreds", "outreach": "DM", "pr_notes": "Streetwear/culture brand + media. Check thehundreds.com/press. Email needed."},
}

print(f"Brand data loaded: {len(BRAND_DATA)} brands")

# ── Read current Personnel and find brand rows ──────────────────────────
print("\nReading Personnel table...")
rows = sheets.get_all_rows('Personnel')
headers = rows[0]
data_rows = rows[1:]

def clean_h(h):
    return re.sub(r'^\[.*?\]\s*', '', h).strip().lower()

clean_headers = [clean_h(h) for h in headers]

def fc(target):
    t = target.lower()
    for i, h in enumerate(clean_headers):
        if h == t: return i
    for i, h in enumerate(clean_headers):
        if t in h: return i
    return None

col_name = fc('name')
col_brand = fc('brand')
col_ig = fc('instagram handle')
col_outreach = fc('outreach method')
col_notes = fc('outreach notes')
col_tags = fc('tags')

print(f"  Name col: {col_name}")
print(f"  Brand col: {col_brand}")
print(f"  Instagram Handle col: {col_ig}")
print(f"  Outreach Method col: {col_outreach}")
print(f"  Notes col: {col_notes}")

# Find brand PR rows and build updates
updates = []
updated_count = 0
not_found = []

for i, row in enumerate(data_rows, start=2):  # row 2 is first data row
    name = row[col_name].strip() if col_name < len(row) else ''
    if not name.endswith(' PR'):
        continue

    brand_name = name[:-3].strip()  # Remove " PR" suffix
    if brand_name not in BRAND_DATA:
        not_found.append(brand_name)
        continue

    bd = BRAND_DATA[brand_name]

    # Update Instagram Handle
    if col_ig is not None:
        current_ig = row[col_ig].strip() if col_ig < len(row) else ''
        if not current_ig:
            updates.append((i, col_ig + 1, bd['ig']))

    # Update Outreach Method
    if col_outreach is not None:
        current_outreach = row[col_outreach].strip() if col_outreach < len(row) else ''
        if not current_outreach:
            updates.append((i, col_outreach + 1, bd['outreach']))

    # Update Notes with PR agency info
    if col_notes is not None:
        current_notes = row[col_notes].strip() if col_notes < len(row) else ''
        pr_info = bd['pr_notes']
        if pr_info and pr_info not in current_notes:
            new_notes = f"{current_notes} | {pr_info}" if current_notes else pr_info
            updates.append((i, col_notes + 1, new_notes))

    updated_count += 1

print(f"\n── Update Summary ──")
print(f"  Brand rows found: {updated_count}")
print(f"  Cell updates queued: {len(updates)}")
if not_found:
    print(f"  Not found in data: {not_found[:10]}")

# Execute updates in batches (Google Sheets API limit)
BATCH_SIZE = 500
if updates:
    for batch_start in range(0, len(updates), BATCH_SIZE):
        batch = updates[batch_start:batch_start + BATCH_SIZE]
        print(f"  Writing batch {batch_start//BATCH_SIZE + 1} ({len(batch)} cells)...")
        sheets.batch_update_cells('Personnel', batch)

    sheets._invalidate_cache('Personnel')
    print(f"\nDone! Updated {updated_count} brand records with Instagram handles, outreach methods, and PR notes.")
else:
    print("\nNo updates needed.")

print(f"\n── Sections C, D, E Complete ──")
print(f"  Instagram handles set: {updated_count}")
print(f"  Outreach methods set: {updated_count}")
print(f"  PR contact notes added: {updated_count}")
