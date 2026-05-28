//
// analyzer module producing DQM histograms for Stm subsystem
//
//


#include "art/Framework/Core/EDAnalyzer.h"
#include "art/Framework/Core/ModuleMacros.h"
#include "art/Framework/Principal/Event.h"
#include "art_root_io/TFileService.h"

#include "Offline/RecoDataProducts/inc/STMWaveformDigi.hh"
#include "Offline/DataProducts/inc/STMChannel.hh" 
#include "Offline/Mu2eUtilities/inc/STMUtils.hh"
#include "Offline/ProditionsService/inc/ProditionsHandle.hh"
#include "Offline/RecoDataProducts/inc/STMPHDigi.hh"

#include "TH1F.h"

#include <string>
#include <vector>

namespace mu2e {

class DqmStm : public art::EDAnalyzer {
 public:
  struct Config {
    using Name = fhicl::Name;
    using Comment = fhicl::Comment;
    //fhicl::Atom<art::InputTag> stmwaveformDigisTag{Name("stmWaveformDigisTag"), Comment("InputTag for STMWaveformDigiCollection")};
    fhicl::Atom<art::InputTag> phHPGeTag{Name("phHPGeTag"), Comment("StmDigi phHPge Collection"), art::InputTag()};
    fhicl::Atom<art::InputTag> phLaBrTag{Name("phLaBrTag"), Comment("StmDigi phLaBr Collection"), art::InputTag()};

  };
  typedef art::EDAnalyzer::Table<Config> Parameters;

  explicit DqmStm(const Parameters& conf);
  virtual ~DqmStm() {}

  virtual void beginJob();
  virtual void endJob(){};
  virtual void analyze(const art::Event& e);

private:
  Config _conf;

  TH1D* _hVer;

  // PH digis
  TH1D* _hNPHHPGe; //Number of pulse heights for HPGe
  TH1D* _hPulseHeightHPGe; //Pulse Heigt of HPGe

  TH1D* _hNPHLaBr; //Number of pulse heights for LaBr                                                                        
  TH1D* _hPulseHeightLaBr; //Pulse Heigt of LaBr
  
  // For later
  //Th1D* _hRawCount;
  //TH1D* _hZSCount;
  
};
/*****************************/
  // configrues fcl to local variables  
DqmStm::DqmStm(const Parameters& conf) : art::EDAnalyzer(conf), _conf(conf()) {
  mayConsume<STMPHDigiCollection>(_conf.phHPGeTag()); //reads PH from the art file given in fcl
  mayConsume<STMPHDigiCollection>(_conf.phLaBrTag());
  //Will add more in time such as raw, zs, frag count etc. 
}

/*****************************************/
  // makes the hist -> working with _hNPH and _hPulseHeights
void DqmStm::beginJob() {
  art::ServiceHandle<art::TFileService> tfs;
  
  _hVer = tfs->make<TH1D>("Ver", "Version Number", 101, -0.5, 100.00);
  
  if (!_conf.phHPGeTag().empty()){
    _hNPHHPGe = tfs->make<TH1D>("NPHDigisHPGe", "N PH HPGe Digis", 101, -0.5, 100.5);
    _hPulseHeightHPGe = tfs->make<TH1D>("PulseHeightHPGe", "STM HPGe Pulse Height", 1000, 0.0, 10000.0);
  }

  if (!_conf.phLaBrTag().empty()){
    _hNPHLaBr = tfs->make<TH1D>("NPHDigisLaBr", "N PH LaBr Digis", 101, -0.5, 100.5);
    _hPulseHeightLaBr = tfs->make<TH1D>("PulseHeightLaBr", "STM LaBr Pulse Height", 1000, 0.0, 10000.0);
  }
  
}

/************************************/
  // Filling the histograms
void DqmStm::analyze(const art::Event& event) {
  _hVer->Fill(0.0);

  if (!_conf.phHPGeTag().empty()) {
    auto phDigiHandle = event.getValidHandle<STMPHDigiCollection>(_conf.phHPGeTag());
    const auto& phDigis = *phDigiHandle;
    
    _hNPHHPGe->Fill(phDigis.size());
    
    for (const auto& phDigi : phDigis) {
      _hPulseHeightHPGe->Fill(phDigi.energy());
    }
    
  }
  

  if (!_conf.phLaBrTag().empty()) {
    auto phDigiHandle = event.getValidHandle<STMPHDigiCollection>(_conf.phLaBrTag());
    const auto& phDigis = *phDigiHandle;
    
    _hNPHLaBr->Fill(phDigis.size());
    
    for (const auto& phDigi: phDigis) {
      _hPulseHeightLaBr->Fill(phDigi.energy());
    }
    
  }
  
  
}
} //namespace mu2e
  
DEFINE_ART_MODULE(mu2e::DqmStm)
